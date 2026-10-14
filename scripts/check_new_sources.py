"""Do the newly enabled sources actually return items?

"Enabled" is a claim about intent. This checks the outcome, because the failure mode this
project keeps hitting is a source that reports HTTP 200 and contributes nothing -- it looks
collected in every summary and adds zero rows to the digest.

Run after changing sources/overrides.yaml.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from aidaily.config import load_config  # noqa: E402
from aidaily.fetchers import get_fetcher  # noqa: E402
from aidaily.http import HttpClient  # noqa: E402
from aidaily.registry import apply_overrides, load_overrides, load_registry  # noqa: E402


async def main() -> int:
    cfg = load_config(env={})
    sources, _ = apply_overrides(load_registry(), load_overrides())

    # Only the sources this change touched: the HtmlFetcher pair and the eight presets.
    watch = [s for s in sources if s.enabled and (
        s.adapter == "HtmlFetcher"
        or s.source_id.startswith("rss:developer-nvidia")
        or s.source_id.startswith("rss:vllm")
        or s.source_id.startswith("rss:lendangregg")
        or s.source_id.startswith("rss:brendangregg")
        or s.source_id.startswith("rss:lwn-net-headlines")
        or s.source_id.startswith("rss:mshibanami")
        or s.source_id.startswith("rss:seangoedecke")
        or s.source_id.startswith("rss:search-cnbc")
        or s.source_id.startswith("rss:hackaday")
    )]

    print(f"检查 {len(watch)} 个新启用/改适配器的源\n")
    ok = empty = failed = 0
    async with HttpClient() as http:
        for spec in watch:
            fetcher = get_fetcher(spec, http)
            if fetcher is None:
                print(f"  {'无适配器':8} {spec.source_id[:56]}")
                failed += 1
                continue
            try:
                result = await fetcher.safe_fetch(spec)
            except Exception as exc:  # noqa: BLE001
                print(f"  {'异常':8} {spec.source_id[:56]}  {type(exc).__name__}")
                failed += 1
                continue

            n = len(result.items)
            if not result.ok:
                print(f"  {'请求失败':8} {spec.source_id[:56]}  {result.detail[:40]}")
                failed += 1
            elif n == 0:
                print(f"  {'0 条':8} {spec.source_id[:56]}  {result.detail[:40]}")
                empty += 1
            else:
                sample = result.items[0].title[:44]
                print(f"  {'ok':8} {spec.source_id[:56]}  {n:3} 条  {sample}")
                ok += 1

    print(f"\n  有内容 {ok} · 空 {empty} · 失败 {failed}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
