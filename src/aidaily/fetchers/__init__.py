"""Fetcher registry and adapter resolution.

`resolve_adapter` is the single place that decides how a source is fetched, and it is
used both to run the fetch and to decide whether a source is collectable. That matters:
if the two disagreed, a source could be counted as "will be collected" and then quietly
produce nothing.
"""

from __future__ import annotations

from ..http import HttpClient
from ..models import SourceSpec
from .base import BaseFetcher, SourceResult
from .github_trending import GitHubTrendingFetcher
from .html import HtmlFetcher
from .jsonapi import JsonApiFetcher
from .reddit import RedditFetcher, json_url_to_html
from .rss import RssFetcher
from .tavily import TavilyFetcher
from .x_timeline import XTimelineFetcher

#: adapter name (as written in sources/registry.yaml) -> implementation
ADAPTERS: dict[str, type[BaseFetcher]] = {
    "RssFetcher": RssFetcher,
    "JsonFeedFetcher": RssFetcher,          # JSON Feed goes through the same parser
    "RedditFetcher": RedditFetcher,
    "JsonApiFetcher": JsonApiFetcher,
    "GitHubTrendingFetcher": GitHubTrendingFetcher,
    "HtmlFetcher": HtmlFetcher,
    "TavilyFetcher": TavilyFetcher,
    "XTimelineFetcher": XTimelineFetcher,
}

#: fallback when the registry names an adapter we do not have yet
_BY_SOURCE_TYPE = {
    "rss": "RssFetcher",
    "atom": "RssFetcher",
    "jsonfeed": "JsonFeedFetcher",
    "api": "JsonApiFetcher",
    # A scrape source is HTML by definition. Without this it fell through to the JSON
    # parser, which cannot read HTML -- so a page that fetched fine produced zero items and
    # looked healthy.
    "scrape": "HtmlFetcher",
    "web": "HtmlFetcher",
    # An X account timeline: no API key, one request per handle.
    "x_timeline": "XTimelineFetcher",
}

#: Names the *registry generator* assigns in bulk, i.e. "no specific adapter chosen".
#: A human naming anything else is stating a requirement.
#:
#: `HtmlFetcher` used to be listed here as a placeholder, because it did not exist yet: the
#: generator wrote it for every scrape source and the resolver swapped it for the generic
#: JSON parser. It is now implemented, so naming it means what it says.
_PLACEHOLDER_ADAPTERS = {"ApiFetcher", "FeedFetcher", ""}


def resolve_adapter(spec: SourceSpec) -> str | None:
    """Which adapter will handle this source, or None if none is implemented.

    Returning None is a first-class outcome: the collector reports it as an explicit
    skip with a reason instead of silently collecting nothing.

    An adapter named explicitly in sources/overrides.yaml is never silently swapped for
    a generic one. That fallback was a real bug: `adapter: PyTrendsFetcher` on the
    Google Trends source was ignored, the generic JSON parser ran against an HTML page,
    and the run reported a healthy HTTP 200 with zero items -- a source that looked
    collected but contributed nothing.
    """
    if spec.adapter in ADAPTERS:
        return spec.adapter
    if spec.adapter in _PLACEHOLDER_ADAPTERS:
        return _BY_SOURCE_TYPE.get(spec.source_type)
    return None


def get_fetcher(spec: SourceSpec, http: HttpClient) -> BaseFetcher | None:
    name = resolve_adapter(spec)
    return ADAPTERS[name](http) if name else None


__all__ = [
    "ADAPTERS",
    "BaseFetcher",
    "GitHubTrendingFetcher",
    "HtmlFetcher",
    "JsonApiFetcher",
    "RedditFetcher",
    "RssFetcher",
    "TavilyFetcher",
    "SourceResult",
    "get_fetcher",
    "json_url_to_html",
    "resolve_adapter",
]
