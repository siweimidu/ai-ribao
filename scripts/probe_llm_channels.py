#!/usr/bin/env python3
"""Probe LLM channels at minimum cost.

Cost strategy -- this is the whole point of the script:

1. **`GET {base}/models` instead of a chat completion.** Listing models consumes no
   tokens on every provider we care about, and one request already answers the two
   questions that matter: is the key accepted, and what can it actually call.
2. **Deduplicate first.** The key file has the same endpoint repeated many times; probing
   a channel twice is pure waste.
3. **A chat fallback is opt-in (`--deep`) and capped at 1 output token.** It exists only
   to distinguish "endpoint is alive but has no /models route" from "endpoint is dead",
   and it is off by default because it is the only step that can spend quota.

Secrecy: keys are never printed and never written. Each channel is identified by the
first 8 hex characters of a SHA-256 of its key, plus the human label from the file.
This script reads the key file from a path you pass in; it never copies it anywhere.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT_JSONL = ROOT / "data" / "state" / "llm_channels.jsonl"
OUT_REPORT = ROOT / "docs" / "LLM_CHANNELS.md"

UA = "ai-daily/0.1 (channel probe)"

# Official / known providers: the key file names them by `platform`, and the endpoint has
# to be filled in because the file only stores the key.
PLATFORM_ENDPOINTS: dict[str, str] = {
    "google": "https://generativelanguage.googleapis.com/v1beta/openai",
    "groq": "https://api.groq.com/openai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "cohere": "https://api.cohere.com/v1",
    "huggingface": "https://router.huggingface.co/v1",
    "mistral": "https://api.mistral.ai/v1",
    "modelscope": "https://api-inference.modelscope.cn/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "opencode": "https://opencode.ai/zen/v1",
    "pollinations": "https://text.pollinations.ai/openai",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "agnes": "https://apihub.agnes-ai.com/v1",
    "ainative": "https://api.ainative.studio/v1",
    "aion": "https://api.aionlabs.ai/v1",
    "bazaarlink": "https://api.bazaarlink.ai/v1",
    "llm7": "https://api.llm7.io/v1",
    "nara": "https://api.nara.ai/v1",
    "navy": "https://api.navy/v1",
    "reka": "https://api.reka.ai/v1",
    "requesty": "https://router.requesty.ai/v1",
    "routeway": "https://api.routeway.ai/v1",
    "sealion": "https://api.sea-lion.ai/v1",
    "ollama": "https://ollama.com/v1",
    # Cloudflare Workers AI uses `account_id:token` and a per-account path.
    "cloudflare": "https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1",
    # GitHub Models needs a GitHub PAT and has a different host.
    "github": "https://models.github.ai/inference",
}

# Suffixes that must be stripped: we build `{base}/models` ourselves.
_STRIP_SUFFIXES = ("/chat/completions", "/completions", "/models", "/responses")


def canonical_base(raw: str) -> str:
    """Normalise a base URL so `{base}/models` is the right thing to call.

    The key file mixes conventions: some entries point at `.../v1`, some at
    `.../v1/chat/completions`, one at `.../openai` with no version. Getting this wrong
    would report a working channel as dead.
    """
    raw = (raw or "").strip().rstrip("/")
    if not raw:
        return ""
    low = raw.lower()
    for suffix in _STRIP_SUFFIXES:
        if low.endswith(suffix):
            raw = raw[: -len(suffix)].rstrip("/")
            low = raw.lower()
            break
    if not urlsplit(raw).scheme:
        raw = "https://" + raw
    return raw


def channel_id(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


@dataclass
class Channel:
    cid: str
    label: str
    base: str
    key: str
    platform: str = ""
    verdict: str = "pending"
    status: int | None = None
    latency_ms: int = 0
    model_count: int = 0
    sample_models: list[str] = field(default_factory=list)
    detail: str = ""
    probes: int = 0          # number of HTTP requests actually made
    tokens_spent: int = 0    # always 0 unless --deep


def load_channels(path: Path, include_unmapped: bool) -> tuple[list[Channel], list[str]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    seen: dict[tuple[str, str], Channel] = {}
    skipped: list[str] = []

    for row in doc.get("keys") or []:
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        platform = str(row.get("platform") or "").strip().lower()
        label = str(row.get("label") or platform or "custom").strip() or "custom"

        base = canonical_base(row.get("baseUrl") or "")
        if not base and platform in PLATFORM_ENDPOINTS:
            base = PLATFORM_ENDPOINTS[platform]
            if platform == "cloudflare" and ":" in key:
                account, _, token = key.partition(":")
                base = base.format(account=account)
                key = token
        if not base:
            if include_unmapped:
                skipped.append(f"{label}: no endpoint known for platform {platform!r}")
            continue
        if "{account}" in base:
            skipped.append(f"{label}: cloudflare entry without account id")
            continue

        dedup_key = (base, key)
        if dedup_key in seen:
            # Same endpoint and same key under another label: probing again is waste.
            existing = seen[dedup_key]
            if label not in existing.label:
                existing.label = f"{existing.label} / {label}"
            continue
        seen[dedup_key] = Channel(cid=channel_id(key), label=label, base=base, key=key, platform=platform)

    return list(seen.values()), skipped


async def probe_models(client: httpx.AsyncClient, ch: Channel, timeout: float) -> None:
    """One request: `GET {base}/models`. No tokens."""
    url = f"{ch.base}/models"
    start = time.monotonic()
    ch.probes += 1
    try:
        resp = await client.get(url, headers={"Authorization": f"Bearer {ch.key}"}, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        ch.verdict = "unreachable"
        ch.detail = f"{type(exc).__name__}: {exc}"[:160]
        ch.latency_ms = int((time.monotonic() - start) * 1000)
        return

    ch.latency_ms = int((time.monotonic() - start) * 1000)
    ch.status = resp.status_code

    if resp.status_code == 200:
        try:
            doc = resp.json()
        except Exception:  # noqa: BLE001
            ch.verdict = "bad_payload"
            ch.detail = "200 but the body is not JSON"
            return
        ids = _model_ids(doc)
        ch.model_count = len(ids)
        ch.sample_models = ids[:6]
        ch.verdict = "ok" if ids else "ok_no_models"
        ch.detail = f"{len(ids)} model(s)"
        return

    if resp.status_code in (401, 403):
        ch.verdict = "unauthorized"
        ch.detail = f"HTTP {resp.status_code}: key rejected"
    elif resp.status_code == 404:
        ch.verdict = "no_models_route"
        ch.detail = "HTTP 404: /models not exposed"
    elif resp.status_code == 429:
        ch.verdict = "rate_limited"
        ch.detail = "HTTP 429"
    else:
        ch.verdict = "error"
        ch.detail = f"HTTP {resp.status_code} {resp.reason_phrase}"


def _model_ids(doc: object) -> list[str]:
    """Models arrive as OpenAI `{data:[{id}]}`, `{models:[...]}`, a bare list, or Gemini's shape."""
    rows: list = []
    if isinstance(doc, dict):
        for key in ("data", "models", "result"):
            if isinstance(doc.get(key), list):
                rows = doc[key]
                break
    elif isinstance(doc, list):
        rows = doc
    out: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            for key in ("id", "name", "model", "model_name"):
                if isinstance(row.get(key), str):
                    out.append(row[key])
                    break
        elif isinstance(row, str):
            out.append(row)
    return out


async def probe_chat(client: httpx.AsyncClient, ch: Channel, timeout: float, model: str) -> None:
    """Opt-in fallback: a chat request capped at ONE output token.

    This is the only step that can spend quota, so it runs solely under --deep and only
    for channels where /models was inconclusive.
    """
    url = f"{ch.base}/chat/completions"
    start = time.monotonic()
    ch.probes += 1
    try:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {ch.key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        ch.verdict = "unreachable"
        ch.detail = f"{type(exc).__name__}: {exc}"[:160]
        return
    ch.latency_ms = int((time.monotonic() - start) * 1000)
    ch.status = resp.status_code
    if resp.status_code == 200:
        ch.verdict = "ok_chat"
        ch.tokens_spent += 1
        ch.detail = f"chat ok ({model})"
    elif resp.status_code in (401, 403):
        ch.verdict = "unauthorized"
        ch.detail = f"HTTP {resp.status_code}"
    elif resp.status_code == 429:
        ch.verdict = "rate_limited"
        ch.detail = "HTTP 429"
    else:
        ch.verdict = "error"
        ch.detail = f"HTTP {resp.status_code} {resp.reason_phrase}"


async def main_async(args: argparse.Namespace) -> int:
    path = Path(args.keys)
    if not path.exists():
        print(f"key file not found: {path}")
        return 1
    channels, skipped = load_channels(path, include_unmapped=False)
    print(f"channels after de-duplication: {len(channels)}   (skipped: {len(skipped)})")
    for s in skipped[:10]:
        print(f"  skip  {s}")

    if args.deep:
        print("\n!! --deep is on: the chat fallback will spend a few tokens per channel")

    sem = asyncio.Semaphore(args.concurrency)
    limits = httpx.Limits(max_connections=args.concurrency * 2)
    async with httpx.AsyncClient(follow_redirects=True, headers={"User-Agent": UA}, limits=limits) as client:

        async def run(ch: Channel) -> None:
            async with sem:
                await probe_models(client, ch, args.timeout)
                if args.deep and ch.verdict in ("no_models_route", "error", "bad_payload"):
                    await probe_chat(client, ch, args.timeout, args.deep_model)

        await asyncio.gather(*(run(c) for c in channels))

    channels.sort(key=lambda c: (c.verdict not in ("ok", "ok_chat", "ok_no_models"), c.label.lower()))

    OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    with OUT_JSONL.open("a", encoding="utf-8") as fh:
        for ch in channels:
            fh.write(json.dumps({
                "probed_at": stamp, "channel": ch.cid, "label": ch.label,
                "base_url": ch.base, "platform": ch.platform, "verdict": ch.verdict,
                "http_status": ch.status, "latency_ms": ch.latency_ms,
                "model_count": ch.model_count, "sample_models": ch.sample_models,
                "detail": ch.detail, "probes": ch.probes, "tokens_spent": ch.tokens_spent,
            }, ensure_ascii=False) + "\n")

    counts: dict[str, int] = {}
    for ch in channels:
        counts[ch.verdict] = counts.get(ch.verdict, 0) + 1
    total_probes = sum(c.probes for c in channels)
    total_tokens = sum(c.tokens_spent for c in channels)

    write_report(channels, counts, stamp, total_probes, total_tokens, len(skipped))
    print(f"\nverdicts: {counts}")
    print(f"HTTP requests: {total_probes}   tokens spent: {total_tokens}")
    print(f"wrote {OUT_JSONL.relative_to(ROOT)}")
    print(f"wrote {OUT_REPORT.relative_to(ROOT)}")
    return 0


def write_report(channels, counts, stamp, probes, tokens, n_skipped) -> None:
    lines = [
        "# LLM 渠道可用性实测报告",
        "",
        f"探测时间：{stamp}",
        f"总 HTTP 请求：**{probes}**　消耗 token：**{tokens}**　未识别端点而跳过：{n_skipped}",
        "",
        "> 方法：用 `GET {base}/models` 判断 key 是否可用 —— **列模型不消耗 token**。",
        "> 对话回退仅在 `--deep` 时启用且 `max_tokens=1`。",
        "> 密钥不落盘、不打印；每个渠道用 key 的 SHA-256 前 8 位标识。",
        "",
        "## 结论分布",
        "",
        "| 判定 | 数量 | 含义 |",
        "|---|---|---|",
        f"| ok | {counts.get('ok', 0)} | 200 且列出模型 —— **可直接用** |",
        f"| ok_no_models | {counts.get('ok_no_models', 0)} | 200 但模型列表为空 |",
        f"| ok_chat | {counts.get('ok_chat', 0)} | /models 不可用，但对话可用（--deep） |",
        f"| unauthorized | {counts.get('unauthorized', 0)} | key 被拒（401/403） |",
        f"| no_models_route | {counts.get('no_models_route', 0)} | 无 /models 路由，未深测 |",
        f"| rate_limited | {counts.get('rate_limited', 0)} | 429 |",
        f"| error | {counts.get('error', 0)} | 其它 HTTP 错误 |",
        f"| unreachable | {counts.get('unreachable', 0)} | DNS/TLS/超时 |",
        f"| bad_payload | {counts.get('bad_payload', 0)} | 200 但响应不是 JSON |",
        "",
    ]
    usable = [c for c in channels if c.verdict in ("ok", "ok_chat")]
    if usable:
        lines += ["## ✅ 可用渠道", "", "| 渠道 | 端点 | 模型数 | 延迟 | 示例模型 |", "|---|---|---|---|---|"]
        for c in usable:
            sample = ", ".join(c.sample_models[:3])[:70]
            lines.append(f"| {c.label[:28]} | {c.base[:52]} | {c.model_count} | {c.latency_ms}ms | {sample} |")
        lines.append("")

    for verdict, title in (
        ("unauthorized", "🔑 key 被拒"),
        ("unreachable", "❌ 不可达"),
        ("no_models_route", "❔ 无 /models 路由"),
        ("rate_limited", "⏳ 限流"),
        ("error", "⚠️ 其它错误"),
    ):
        rows = [c for c in channels if c.verdict == verdict]
        if not rows:
            continue
        lines += [f"## {title}（{len(rows)}）", "", "| 渠道 | 端点 | 状态 | 详情 |", "|---|---|---|---|"]
        for c in rows:
            lines.append(f"| {c.label[:28]} | {c.base[:52]} | {c.status or '-'} | {c.detail[:60]} |")
        lines.append("")

    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="以最低成本探测 LLM 渠道可用性")
    p.add_argument("--keys", required=True, help="密钥 JSON 文件路径（不会被复制或打印）")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--timeout", type=float, default=15.0)
    p.add_argument("--deep", action="store_true", help="对 /models 不确定的渠道发 max_tokens=1 的对话请求（会消耗极少量额度）")
    p.add_argument("--deep-model", default="gpt-4o-mini", help="--deep 时使用的模型名")
    args = p.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
