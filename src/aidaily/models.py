"""Core data models.

These mirror the contracts in docs/ARCHITECTURE.md §5.1. Two rules are load-bearing
and must not be relaxed:

1. `published_at` is optional. A missing publication date stays None -- it is never
   replaced by the fetch time. Several sources in the audit carry no per-item date
   (GitHub Trending's "today" is a star-delta window, not a publication date), and
   inventing one is exactly how a digest starts claiming things that are not true.
2. Every merged item keeps *all* of its URLs and source ids. Deduplication compresses
   records; it must never destroy evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SourceType = Literal["rss", "atom", "jsonfeed", "api", "scrape"]
HealthStatus = Literal[
    "healthy", "degraded", "blocked", "dead", "needs_credential", "disabled", "unverified"
]
AgeBucket = Literal["today", "past_72h", "older", "today_window", "unknown"]
EvidenceLevel = Literal["single_source", "multi_source", "official_confirmed"]


class SourceSpec(BaseModel):
    """One row of sources/registry.yaml."""

    model_config = ConfigDict(extra="allow")

    source_id: str
    name: str
    url: str
    normalized_url: str
    domain: str
    category: str
    language: str | None = None
    source_type: SourceType
    fetch_method: str = "httpx_json"
    adapter: str = "ApiFetcher"
    enabled: bool = True
    priority: int = 3
    polling_interval: str = "6h"
    timeout_s: int = 20
    needs_credential: str | None = None
    dedup_group: str | None = None
    health_status: HealthStatus = "unverified"
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    notes: str | None = None
    # provenance: repo:file#config-key strings, never trimmed
    found_in: list[str] = Field(default_factory=list)
    repositories: list[str] = Field(default_factory=list)
    params: dict[str, Any] | None = None
    merged_parameter_rows: int = 1
    # set when sources/overrides.yaml changed something; keeps the human decision visible
    override_reason: str | None = None
    overridden_fields: list[str] = Field(default_factory=list)


class RawItem(BaseModel):
    """What an adapter returns before normalization. Deliberately loose."""

    model_config = ConfigDict(extra="allow")

    source_id: str
    title: str = ""
    url: str = ""
    published_at: datetime | None = None
    summary: str = ""
    content_text: str | None = None
    author: str | None = None
    language: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    native_id: str | None = None


class NormalizedItem(BaseModel):
    """A cleaned, fingerprint-bearing item. This is what dedup operates on."""

    model_config = ConfigDict(extra="allow")

    item_id: str
    source_id: str
    title: str
    title_norm: str
    url: str
    canonical_url: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime
    first_seen_at: datetime
    updated_at: datetime
    language: str | None = None
    summary: str = ""
    content_text: str | None = None
    content_sha256: str
    simhash: int
    author: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    age_bucket: AgeBucket = "unknown"
    dup_group_id: str | None = None
    event_id: str | None = None
    also_seen_in: list[str] = Field(default_factory=list)

    @field_validator("published_at", "fetched_at", "first_seen_at", "updated_at")
    @classmethod
    def _require_tz(cls, v: datetime | None) -> datetime | None:
        """Naive datetimes are a bug source across timezones; force UTC awareness."""
        if v is None:
            return None
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


class DupGroup(BaseModel):
    """L2 result: several records believed to be the SAME article."""

    dup_group_id: str
    primary_item_id: str
    member_item_ids: list[str]
    all_urls: list[str]
    source_ids: list[str]
    title: str
    published_at: datetime | None = None
    first_seen_at: datetime
    updated_at: datetime
    merged_content: str = ""
    domain: str = ""
    # how the merge was justified -- kept for auditing false merges
    matched_by: list[str] = Field(default_factory=list)
    confidence: float = 1.0


class AmbiguousPair(BaseModel):
    """Two items that look similar but were deliberately NOT merged.

    Kept so the decision is reviewable: over-merging destroys information, so a
    similar-but-not-identical pair is surfaced rather than silently collapsed.
    """

    left_item_id: str
    right_item_id: str
    similarity: float
    reason: str


class Event(BaseModel):
    """L3 result: several different articles reporting the SAME event."""

    event_id: str
    title: str
    member_item_ids: list[str]
    primary_item_id: str
    source_ids: list[str]
    all_urls: list[str]
    #: distinct `dedup_group`s among the sources. Two feeds that carry the same content
    #: (HN Algolia and hnrss frontpage) are one source, not two -- counting them
    #: separately would manufacture false corroboration.
    independent_source_count: int = 0
    first_seen_at: datetime
    last_updated_at: datetime
    published_range: tuple[datetime, datetime] | None = None
    unique_facts: dict[str, list[str]] = Field(default_factory=dict)
    confidence: float = 1.0
    evidence_level: EvidenceLevel = "single_source"
    #: Absolute URL of the story image, or None. Set by the image stage *after* selection, so
    #: only published stories are ever fetched. Absolute rather than relative on purpose: the
    #: media repository can roll over to a new one, and an old page must keep pointing at the
    #: repository that actually holds its picture.
    #: Absolute URLs of the story pictures, best first. A story often has several -- a hero, a
    #: diagram, a screenshot -- and the layout shows them side by side, each in its own
    #: proportions. Empty means the renderer draws a placeholder.
    image_urls: list[str] = Field(default_factory=list)
    needs_review: bool = False
    #: ranking result, kept so a placement can be explained after the fact
    rank_score: float = 0.0
    #: `float | str`, not `float`. The rubric records `rubric_band` ("突破性"), and typing this
    #: as `float` meant **every archived digest failed to load**: `Event.model_validate` raised
    #: `unable to parse string as a number` on a file the pipeline itself had just written.
    #: Everything that reads the archive -- re-ranking, the audit tools, the tests -- broke on
    #: data produced minutes earlier, and it looked like corrupt input rather than a schema
    #: that no longer matched its own writer.
    rank_components: dict[str, float | str] = Field(default_factory=dict)


class SourceCoverage(BaseModel):
    """Honest coverage numbers, written into every digest and shown to readers."""

    total: int = 0
    active: int = 0
    failed: int = 0
    degraded: int = 0
    blocked: int = 0
    skipped: int = 0


class Digest(BaseModel):
    date: str
    kind: Literal["brief", "deep"]
    generated_at: datetime
    window_start: datetime
    window_end: datetime
    headline: str = ""
    top_events: list[Event] = Field(default_factory=list)
    sections: dict[str, list[Event]] = Field(default_factory=dict)
    trend_notes: list[str] = Field(default_factory=list)
    source_coverage: SourceCoverage = Field(default_factory=SourceCoverage)
    llm_usage: dict[str, Any] = Field(default_factory=dict)
    # explicit, reader-visible statement of what is missing -- never empty when data is thin
    warnings: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
