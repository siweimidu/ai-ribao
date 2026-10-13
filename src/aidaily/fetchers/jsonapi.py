"""Generic JSON API fetcher with per-domain field maps.

Covers the audited API endpoints that return a list of records. Each entry in
`_DOMAIN_MAPS` encodes facts read out of the six repositories, not guesses:

* `hn.algolia.com`     -- dailydawn's HackerNews fetcher: hits[], points, num_comments
* `huggingface.co/api/models`   -- likes, lastModified, modelId
* `huggingface.co/api/datasets` -- likes, lastModified, id
* `v2ex.com/api/topics/hot.json`-- replies, created (unix seconds), member.username

An unknown host still works: the generic extractor probes the usual envelope keys and
common field names, so adding a source is often just adding a URL to the registry.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from ..http import HttpClient
from ..models import RawItem, SourceSpec
from .base import BaseFetcher, SourceResult

_ENVELOPE_KEYS = ("hits", "items", "results", "data", "articles", "stories", "posts", "entries")
_TITLE_KEYS = ("title", "name", "modelId", "full_name", "headline")
_URL_KEYS = ("url", "link", "html_url", "web_url", "permalink", "id")
# `created` is V2EX's name for a unix-seconds timestamp and is easy to miss -- leaving
# it out silently dropped every date from that source.
_DATE_KEYS = (
    "created_at", "createdAt", "created", "lastModified", "published_at",
    "published", "date", "updated_at",
)
_SUMMARY_KEYS = ("summary", "description", "tagline", "content", "text", "body")


class JsonApiFetcher(BaseFetcher):
    name = "JsonApiFetcher"

    async def fetch(self, spec: SourceSpec) -> SourceResult:
        url = _with_runtime_params(spec, datetime.now(timezone.utc))
        res = await self.http.get(url)
        base = self.from_http(spec, res)
        if not base.ok or res.verdict == "not_modified":
            return base

        head = res.body[:200].lstrip()
        if head.startswith(b"<?xml") or head.startswith(b"<rss") or head.startswith(b"<feed"):
            # Some endpoints in the audit are typed `api` but actually serve a feed
            # (Google News RSS search is the notable one). Delegating avoids reporting a
            # healthy 100-item feed as a parse failure.
            from .rss import RssFetcher

            base.items = RssFetcher(self.http)._parse_feed(spec, res.body)
            base.detail = f"{base.detail} [xml payload -> feed parser]".strip()
            return base

        try:
            doc = res.body and __import__("json").loads(res.body.decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            base.detail = "response is not valid JSON"
            base.items = []
            return base

        records = _records(doc)
        base.items = [it for r in records if (it := _map_record(spec, r)) is not None]
        return base


def _runtime_params(spec: SourceSpec, now: datetime) -> dict[str, str]:
    """Query parameters that must be computed at fetch time.

    `hn.algolia.com/api/v1/search` without a filter returns the highest-scoring stories
    **of all time**, not recent ones: during the first real run its newest item was seven
    months old. dailydawn's fetcher adds exactly these filters to avoid that ("否则
    Algolia API 会按票数返回 HN 历史上所有高票帖"). The registry URL stays as audited;
    the window is applied here because `created_at_i` depends on the current time.
    """
    if spec.domain == "hn.algolia.com":
        cutoff = int((now - timedelta(hours=48)).timestamp())
        return {
            "tags": "story",
            "numericFilters": f"points>20,created_at_i>{cutoff}",
            "hitsPerPage": "60",
        }
    return {}


def _with_runtime_params(spec: SourceSpec, now: datetime) -> str:
    params = _runtime_params(spec, now)
    if not params:
        return spec.url
    joiner = "&" if "?" in spec.url else "?"
    return f"{spec.url}{joiner}{urlencode(params)}"


def _records(doc: object) -> list[dict]:
    if isinstance(doc, list):
        return [r for r in doc if isinstance(r, dict)]
    if isinstance(doc, dict):
        for key in _ENVELOPE_KEYS:
            value = doc.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    return []


def _first(record: dict, keys: tuple[str, ...]) -> object | None:
    for key in keys:
        if record.get(key) not in (None, "", [], {}):
            return record[key]
    return None


def _map_record(spec: SourceSpec, record: dict) -> RawItem | None:
    title = _first(record, _TITLE_KEYS)
    url = _first(record, _URL_KEYS)

    # Hugging Face: the id IS the resource path, not a URL. The id may arrive under
    # `id` (datasets) or only as `modelId` (models), so fall back to the title -- using
    # a bare None here produced the URL ".../models/None".
    if spec.domain == "huggingface.co" and not str(url).startswith("http"):
        resource_id = url if url is not None else title
        if resource_id is None:
            return None
        kind = "datasets" if "/datasets" in spec.url else "models"
        url = f"https://huggingface.co/{kind}/{resource_id}"

    if not title and isinstance(record.get("member"), dict):
        title = record["member"].get("title") or record["member"].get("username")

    if not title and not url:
        return None
    if not url:
        url = ""
    if not title:
        title = str(url)

    published = _parse_date(_first(record, _DATE_KEYS))

    metrics: dict[str, object] = {}
    for key in ("points", "num_comments", "likes", "replies", "ups", "stars", "forks", "comments"):
        value = record.get(key)
        if isinstance(value, (int, float)):
            metrics[key] = value
    if isinstance(record.get("tags"), list):
        metrics["tags"] = [str(t) for t in record["tags"][:8]]
    if isinstance(record.get("node"), dict) and record["node"].get("title"):
        metrics["node"] = record["node"]["title"]

    summary = _first(record, _SUMMARY_KEYS)
    author = record.get("author")
    if isinstance(author, dict):
        author = author.get("name") or author.get("username")
    if not author and isinstance(record.get("member"), dict):
        author = record["member"].get("username")

    return RawItem(
        source_id=spec.source_id,
        title=str(title).strip()[:500],
        url=str(url),
        published_at=published,
        # Hugging Face exposes no description in list responses; that is a fact about
        # the API, not a parsing failure, so the summary is legitimately empty.
        summary=str(summary).strip()[:2000] if summary else "",
        content_text=None,
        author=str(author) if author else None,
        language=spec.language,
        metrics=metrics,
        native_id=str(record.get("objectID") or record.get("id") or record.get("fullname") or "") or None,
    )


def _parse_date(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):            # unix seconds (V2EX)
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None
