"""Turn the raw key export into a relay file the router can actually use.

The export gives `baseUrl`, `key` and `label` -- **no model**. The router falls back to
`default_model` ("gemini-flash-lite-latest") when a row names none, and none of these
third-party endpoints serve that id, so every row would answer 404 and the fallback text
would be the *only* thing that worked. Rotation across 140 broken endpoints is still zero
usable providers.

Two modes:

* `discover` (default) -- ask each endpoint what it serves and pick a model.
* `--offline` -- reuse the previous discovery cache without any network call.

The output is written **outside the repository** by default. These are credentials; the
project rule is that they never enter git, and a path under the repo is one `git add -A`
away from breaking that.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

import httpx

#: Preference order when an endpoint offers several. Cheap, fast, instruction-following
#: models first: this pipeline makes ~60 short structured calls per run, so latency and
#: availability matter far more than reasoning depth.
MODEL_PREFERENCE = [
    "minimax", "glm", "qwen", "deepseek", "kimi", "moonshot", "yi-", "step-",
    "gpt-oss", "llama", "gemini", "claude", "gpt-3", "gpt-4", "chat",
]

#: Models that cannot answer a chat completion.
EXCLUDE = re.compile(
    r"embed|rerank|whisper|tts|audio|image|vision-only|dall|moderation|ocr|"
    r"stable-diffusion|flux|video|upscal|bge-|gte-",
    re.IGNORECASE,
)


def pick_model(ids: list[str]) -> str | None:
    usable = [m for m in ids if not EXCLUDE.search(m)]
    if not usable:
        return None
    for needle in MODEL_PREFERENCE:
        for model in usable:
            if needle in model.lower():
                return model
    return sorted(usable)[0]


async def discover_one(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, row: dict, *, vendor_first: bool = False
) -> dict:
    """Fill in a model for one relay row.

    The host is identified first, always, and recorded even when it does not change what is
    tried -- "which endpoint is this" is what makes a failure report readable.

    `vendor_first` tries a known vendor's own model names with a one-token completion before
    asking for a listing. It is **off by default**, and that is a measured decision rather
    than a cautious one: enabling it dropped resolution from 111/167 to 81/167, with
    `ConnectError` rising from 3 to 22. The extra requests may simply have met a worse network
    on the run that measured it, so the flag is kept rather than deleted -- but a change whose
    evidence is ambiguous does not get to become the default.
    """
    from aidaily.vendors import identify, looks_like_aggregator

    base = str(row.get("baseUrl") or "").rstrip("/")
    out = dict(row)
    if not base:
        out["_pick_error"] = "no baseUrl"
        return out

    vendor = identify(base)
    aggregator = looks_like_aggregator(base)
    out["_vendor"] = vendor.name if vendor else ("中转站" if aggregator else "")
    headers = {"Authorization": f"Bearer {row.get('key','')}", "Content-Type": "application/json"}

    async with sem:
        # --- 1. Optional: a known vendor's own model names, tried directly -----------------
        #
        # Skipped for a reseller: `newapi.*` and friends proxy arbitrary upstreams, so a
        # first-party model name is a guess, and a guessed name 404s in a way that reads like
        # a bad credential.
        if vendor_first and vendor and vendor.models and not aggregator and not row.get("model"):
            for model in vendor.models[:3]:
                ok, detail = await _try_model(client, base, headers, model)
                if ok:
                    out["model"] = model
                    out["_via"] = f"vendor:{vendor.id}"
                    out.pop("_pick_error", None)
                    return out
                out["_pick_error"] = detail

        # --- 2. Ask the endpoint what it serves ------------------------------------
        for candidate in (base, base + "/v1", re.sub(r"/v1$", "", base)):
            try:
                resp = await client.get(f"{candidate}/models", headers=headers)
            except Exception as exc:  # noqa: BLE001
                out["_pick_error"] = f"{type(exc).__name__}"
                continue
            if resp.status_code != 200:
                out["_pick_error"] = f"HTTP {resp.status_code}"
                continue
            try:
                doc = resp.json()
            except Exception:  # noqa: BLE001
                out["_pick_error"] = "non-json"
                continue
            # A bare list is as common as the OpenAI envelope on these gateways.
            if isinstance(doc, list):
                raw_models = doc
            elif isinstance(doc, dict):
                raw_models = doc.get("data") or doc.get("models") or []
            else:
                out["_pick_error"] = "unexpected json shape"
                continue
            ids = [
                str(m.get("id") if isinstance(m, dict) else m)
                for m in raw_models
                if (m.get("id") if isinstance(m, dict) else m)
            ]
            if not ids:
                out["_pick_error"] = "empty model list"
                continue
            chosen = pick_model(ids)
            if not chosen:
                out["_pick_error"] = "no chat-capable model"
                continue
            out["baseUrl"] = candidate
            out["model"] = chosen
            out["_models"] = len(ids)
            out["_via"] = "probe"
            out.pop("_pick_error", None)
            return out

    return out


async def _try_model(
    client: httpx.AsyncClient, base: str, headers: dict, model: str
) -> tuple[bool, str]:
    """One minimal completion: does this endpoint actually serve this model?

    A `/models` listing being present does not mean a model is callable, so the check is a
    real request with `max_tokens: 1` rather than a listing lookup.
    """
    try:
        resp = await client.post(
            f"{base}/chat/completions", headers=headers,
            json={"model": model, "messages": [{"role": "user", "content": "hi"}],
                  "max_tokens": 1},
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}"
    if resp.status_code == 200:
        return True, ""
    return False, f"{model}: HTTP {resp.status_code}"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("keys", help="原始密钥 JSON（freellmapi-keys 导出）")
    ap.add_argument("--out", required=True, help="输出路径（建议放在仓库之外）")
    ap.add_argument("--cache", default=None, help="探测结果缓存（JSON）")
    ap.add_argument("--offline", action="store_true", help="不联网，只用缓存")
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--retry-failed-after", type=float, default=6.0,
                    help="失败项多少小时后重试（默认 6；设 0 表示每次都重试）")
    ap.add_argument("--vendor-first", action="store_true",
                    help="先试厂商自有模型名（默认关闭；见 discover_one 的说明）")
    args = ap.parse_args()

    doc = json.loads(Path(args.keys).read_text(encoding="utf-8-sig"))
    rows = doc.get("keys") or []
    print(f"  输入 {len(rows)} 条密钥")

    cache_path = Path(args.cache) if args.cache else Path(args.out).with_suffix(".cache.json")
    cache: dict[str, dict] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cache = {}

    if not args.offline:
        sem = asyncio.Semaphore(args.concurrency)
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            # One discovery per (base, key): the same gateway can serve different model
            # sets per account tier.
            todo = []
            # Failures are cached too, with a timestamp.
            #
            # Only successes were remembered before, so every run re-probed every failure --
            # and the failures are mostly endpoints that rate-limited us, so retrying them is
            # what keeps them failing. Measured across three consecutive runs: resolution
            # fell 111 -> 81 -> 78 while `ConnectError` climbed 3 -> 22 -> 18. The discovery
            # was measuring its own load, and the numbers looked like a property of the
            # endpoints.
            fresh_after = time.time() - args.retry_failed_after * 3600
            for row in rows:
                ck = f"{row.get('baseUrl')}|{row.get('key','')[:8]}"
                hit = cache.get(ck)
                if hit is None:
                    todo.append((ck, row))
                    continue
                if hit.get("model"):
                    continue
                # A recent failure: leave it alone. An old one: try again, the limit may
                # have reset.
                if float(hit.get("_failed_at") or 0) >= fresh_after:
                    continue
                todo.append((ck, row))

            skipped = len(rows) - len(todo)
            print(f"  需探测 {len(todo)} 条（缓存命中 {skipped}）")

            done = 0

            async def run(ck: str, row: dict) -> None:
                nonlocal done
                result = await discover_one(client, sem, row, vendor_first=args.vendor_first)
                if not result.get("model"):
                    result["_failed_at"] = time.time()
                cache[ck] = result
                done += 1
                if done % 20 == 0:
                    print(f"    ...{done}/{len(todo)}")

            await asyncio.gather(*(run(ck, row) for ck, row in todo))
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    resolved: list[dict] = []
    for row in rows:
        ck = f"{row.get('baseUrl')}|{row.get('key','')[:8]}"
        hit = cache.get(ck) or {}
        entry = dict(row)
        if hit.get("model"):
            entry["baseUrl"] = hit.get("baseUrl", row.get("baseUrl"))
            entry["model"] = hit["model"]
        else:
            # Keep it, but say why it is expected to fail. Dropping it silently would make
            # the key count in the log disagree with the key file.
            entry["model"] = row.get("model") or ""
            entry["_unusable"] = hit.get("_pick_error", "not discovered")
        # Provenance travels with the row.
        #
        # `_vendor` and `_via` are set by `discover_one` and were being dropped here, because
        # only `baseUrl` and `model` were copied out of the cache -- so the run reported
        # "167 未识别 / 167 未解析" while the data was sitting right there in the same dict.
        for key in ("_vendor", "_via", "_models"):
            if hit.get(key) is not None:
                entry[key] = hit[key]
        resolved.append(entry)

    usable = [r for r in resolved if r.get("model")]
    Path(args.out).write_text(
        json.dumps(resolved, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    hosts = len({r.get("baseUrl") for r in usable})
    print()
    print(f"  可解析模型 {len(usable)}/{len(resolved)} 条，覆盖 {hosts} 个端点")
    print(f"  输出: {args.out}")

    from collections import Counter

    vendors = Counter(r.get("_vendor") or "未识别" for r in resolved)
    print("  端点归属:")
    for name, n in vendors.most_common(12):
        label = name or "未识别"
        print(f"    {n:4}  {label}")

    via = Counter(r.get("_via") or "未解析" for r in resolved)
    print("  解析方式:")
    for name, n in via.most_common():
        print(f"    {n:4}  {name}")

    reasons = Counter(r["_unusable"] for r in resolved if not r.get("model"))
    if reasons:
        print("  未解析原因:")
        for reason, n in reasons.most_common(8):
            print(f"    {n:4}  {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
