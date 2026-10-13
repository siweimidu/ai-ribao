"""Fetcher base: one adapter per access pattern, strict per-source failure isolation.

The isolation rule is the important one. With 53 collectable sources, a single
unhandled exception would abort the whole run and lose every other source's data --
the original `CloudFlare-AI-Insight-Daily` lesson, and why `dailydawn`'s
`BaseFetcher.safe_fetch` wraps everything. Here it is structural: `safe_fetch` is the
only entry point the collector uses, and it cannot raise.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..http import HttpClient, HttpResult
from ..models import RawItem, SourceSpec


@dataclass
class SourceResult:
    """Everything the collector needs to record about one source's attempt."""

    source_id: str
    verdict: str            # ok | not_modified | blocked | dead | empty | skipped
    items: list[RawItem] = field(default_factory=list)
    detail: str = ""
    status: int | None = None

    @property
    def ok(self) -> bool:
        return self.verdict in ("ok", "not_modified")


class BaseFetcher(ABC):
    """A fetcher turns one SourceSpec into RawItems.

    Subclasses implement `fetch`; the collector only ever calls `safe_fetch`.
    """

    #: adapter name as written in sources/registry.yaml
    name: str = "base"

    def __init__(self, http: HttpClient) -> None:
        self.http = http

    @abstractmethod
    async def fetch(self, spec: SourceSpec) -> SourceResult:
        raise NotImplementedError

    async def safe_fetch(self, spec: SourceSpec) -> SourceResult:
        try:
            result = await self.fetch(spec)
        except Exception as exc:  # noqa: BLE001 - isolation is the whole point
            return SourceResult(
                spec.source_id, "dead", detail=f"{type(exc).__name__}: {exc}"[:200]
            )
        if not result.items and result.verdict == "ok":
            result.verdict = "empty"
            result.detail = result.detail or "fetched but parsed 0 items"
        return result

    @staticmethod
    def from_http(spec: SourceSpec, res: HttpResult) -> SourceResult:
        """Translate a transport outcome into a SourceResult (no items yet)."""
        if res.verdict == "ok":
            return SourceResult(spec.source_id, "ok", [], res.detail, res.status)
        if res.verdict == "not_modified":
            return SourceResult(spec.source_id, "not_modified", [], "304 Not Modified", 304)
        return SourceResult(spec.source_id, res.verdict, [], res.detail, res.status)
