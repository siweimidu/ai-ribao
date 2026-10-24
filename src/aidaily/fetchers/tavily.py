"""Tavily search fetcher.

Tavily is a **search API**, not a feed: the query and the result count travel in a POST body,
so there is no URL for `JsonApiFetcher` to fetch. That mismatch is why the source sat disabled
with `adapter: ApiFetcher` -- the registry generator assigns that to anything whose
`source_type` is `api`, and the generic JSON reader then did a plain GET against an endpoint
that requires a body.

Two things this is careful about:

* **The key never leaves the request.** It goes in the `Authorization` header, not the URL and
  not the query string -- a credential in a URL ends up in logs, in `HttpResult.url`, and in
  any error message built from either.
* **What the API returns is a search result, not a published item.** Tavily's `content` is an
  extract it chose, and its `published_date` is frequently absent. `published_at` is therefore
  left `None` when the API does not state one, which the pipeline treats as "unknown
  freshness" rather than "just published" -- the same rule GitHub Trending follows.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..http import HttpClient
from ..models import RawItem, SourceSpec
from .base import BaseFetcher, SourceResult

#: Search queries issued per fetch. The digest is an AI daily, so the queries are the day's
#: angles rather than one broad term -- a single "AI" query returns SEO sludge.
#: **Named vendors, not just "AI model release".**
#:
#: Measured 2026-10-24: Moonshot shipped Kimi K3.1 Pro and the issue did not carry it. The two
#: broad queries below returned nothing about it, and Moonshot publishes no RSS -- its own site
#: and API console said "Kimi K3.1 Pro 已正式发布" while our feeds said nothing. A query that
#: names the lab is the only way to see a release from a company that does not syndicate.
#:
#: Kept short: Tavily bills per request and each query is one call.
DEFAULT_QUERIES = (
    "AI model release announcement",
    "人工智能 大模型 发布",
    "Kimi Moonshot 月之暗面 发布",
    "DeepSeek Qwen 智谱 MiniMax 发布",
    "OpenAI Anthropic Gemini release",
)


class TavilyFetcher(BaseFetcher):
    name = "TavilyFetcher"

    async def fetch(self, spec: SourceSpec) -> SourceResult:
        import os

        params = spec.params or {}
        key_env = str(params.get("key_env") or "TAVILY_API_KEY")
        key = os.environ.get(key_env, "")

        # **No GET probe.** Tavily's search endpoint only accepts POST, so `self.http.get(url)`
        # returns 401 and `from_http` would mark the whole fetch failed -- while the POST
        # queries that followed were succeeding and returning items. Measured: `ok=False
        # ... HTTP 401 Unauthorized [2 queries -> 16 items]`, a result that reported failure
        # and carried sixteen good rows.
        #
        # The stale-result cache (`self.validators`) is keyed by URL and is meaningless here
        # anyway: the same URL with a different query body is a different request.
        if not key:
            # An explicit skip naming the variable: a missing credential and a broken endpoint
            # need different responses, and "0 items" says neither.
            return SourceResult(
                spec.source_id, "blocked", [],
                f"{key_env} 未配置（TAVILY_API_KEY 需经环境变量注入）", None,
            )

        base = SourceResult(spec.source_id, "ok", [], "", 200)

        queries = params.get("queries") or list(DEFAULT_QUERIES)
        per_query = int(params.get("max_results") or 10)
        days = int(params.get("days") or 2)
        seen: set[str] = set()
        failures: list[str] = []

        for query in queries:
            body = {
                "query": str(query),
                "max_results": per_query,
                "topic": "news",
                "days": days,
                "search_depth": "basic",
            }
            resp = await self.http.post_json(
                spec.url, body, headers={"Authorization": f"Bearer {key}"}
            )
            if not resp.ok:
                failures.append(f"{resp.status or resp.verdict}")
                continue
            try:
                import json

                doc = json.loads(resp.body)
            except ValueError:
                failures.append("non-json")
                continue

            for row in doc.get("results") or []:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url") or "").strip()
                title = str(row.get("title") or "").strip()
                if not url or not title or url in seen:
                    continue
                seen.add(url)
                base.items.append(RawItem(
                    source_id=spec.source_id,
                    title=title[:300],
                    url=url,
                    published_at=_parse_date(row.get("published_date")),
                    summary=str(row.get("content") or "")[:2000],
                    content_text=None,
                    author=None,
                    language=spec.language,
                    # Tavily's own relevance ranking -- the only ordering signal it gives, and
                    # the order the results arrive in.
                    metrics={"tavily_score": float(row.get("score") or 0.0)},
                    native_id=url,
                ))

        if not base.items:
            # Nothing came back from any query: that *is* a failure, and it should read as one
            # rather than as a source that legitimately had no news.
            base.verdict = "empty"
            base.detail = f"全部查询失败：{', '.join(failures) or '未知'}"
            return base

        base.detail = f"{len(queries)} 次查询 -> {len(base.items)} 条"
        if failures:
            base.detail += f"（{len(failures)} 次失败：{', '.join(failures[:3])}）"
        return base


def _parse_date(value: object) -> datetime | None:
    """Tavily's `published_date`, or None.

    None is the honest answer when the API omits it: the pipeline treats an unknown date as
    neutral freshness, whereas stamping the fetch time would claim the story was published
    today.
    """
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text[: len(fmt) + 2], fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=timezone.utc)
    return None
