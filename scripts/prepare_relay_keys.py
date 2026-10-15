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
    client: httpx.AsyncClient, sem: asyncio.Semaphore, row: dict
) -> dict:
    base = str(row.get("baseUrl") or "").rstrip("/")
    out = dict(row)
    if not base:
        out["_pick_error"] = "no baseUrl"
        return out

    async with sem:
        # Some gateways need a trailing /v1 that the export omits, and some forbid it.
        for candidate in (base, base + "/v1", re.sub(r"/v1$", "", base)):
            try:
                resp = await client.get(
                    f"{candidate}/models",
                    headers={"Authorization": f"Bearer {row.get('key','')}"},
                )
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
            out.pop("_pick_error", None)
            return out

    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("keys", help="原始密钥 JSON（freellmapi-keys 导出）")
    ap.add_argument("--out", required=True, help="输出路径（建议放在仓库之外）")
    ap.add_argument("--cache", default=None, help="探测结果缓存（JSON）")
    ap.add_argument("--offline", action="store_true", help="不联网，只用缓存")
    ap.add_argument("--concurrency", type=int, default=10)
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
            for row in rows:
                ck = f"{row.get('baseUrl')}|{row.get('key','')[:8]}"
                if ck in cache and cache[ck].get("model"):
                    continue
                todo.append((ck, row))
            print(f"  需探测 {len(todo)} 条（缓存命中 {len(rows)-len(todo)}）")

            done = 0
            async def run(ck: str, row: dict) -> None:
                nonlocal done
                result = await discover_one(client, sem, row)
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
    for name, n in vendors.most_common(10):
        print(f"    {n:4}  {name or "未识别"}")

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
