"""Fact checking: reject a digest that asserts something the input does not support.

The rule this enforces is blunt: **the model may not introduce a URL or a date.** Every
link in the output is reconstructed from our own records, and this module proves it by
checking the produced digest against the items it was built from. Any violation fails the
run's publication gate rather than being silently rendered.

The distinction between facts, inferences and opinions is checked structurally, not
semantically: we cannot verify that a sentence is true, but we can refuse to publish a
digest where the three are blended into one list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import Digest, Event, NormalizedItem


@dataclass
class Violation:
    kind: str
    detail: str
    event_id: str | None = None


@dataclass
class FactCheckReport:
    violations: list[Violation] = field(default_factory=list)
    checked_events: int = 0
    checked_urls: int = 0

    @property
    def ok(self) -> bool:
        return not self.violations

    def summary(self) -> dict[str, object]:
        by_kind: dict[str, int] = {}
        for v in self.violations:
            by_kind[v.kind] = by_kind.get(v.kind, 0) + 1
        return {
            "ok": self.ok,
            "checked_events": self.checked_events,
            "checked_urls": self.checked_urls,
            "violations": len(self.violations),
            "by_kind": by_kind,
        }


def check_digest(
    digest: Digest,
    source_items: list[NormalizedItem],
    *,
    allow_singletons: bool = True,
) -> FactCheckReport:
    """Validate a digest against the items it claims to summarise."""
    report = FactCheckReport()

    known_urls = {i.url for i in source_items if i.url}
    known_urls |= {i.canonical_url for i in source_items if i.canonical_url}
    known_ids = {i.item_id for i in source_items}
    known_dates = {i.published_at for i in source_items if i.published_at}
    # The reference point is the digest's own generation time, not the wall clock: a
    # replay of stored data must reach the same verdict whenever it is run, and
    # "future" means "after this digest was produced", not "after right now".
    now = digest.generated_at

    for event in _all_events(digest):
        report.checked_events += 1
        report.checked_urls += len(event.all_urls)

        if not event.all_urls:
            report.violations.append(Violation("event_without_url", "事件没有任何来源链接", event.event_id))

        for url in event.all_urls:
            if url not in known_urls:
                report.violations.append(
                    Violation("fabricated_url", f"链接不在输入数据中：{url[:100]}", event.event_id)
                )

        unknown_members = [m for m in event.member_item_ids if m not in known_ids]
        if unknown_members:
            report.violations.append(
                Violation("unknown_member", f"引用了不存在的条目：{unknown_members[:3]}", event.event_id)
            )

        if event.published_range:
            start, end = event.published_range
            for when in (start, end):
                if when > now:
                    report.violations.append(
                        Violation("future_date", f"发布日期在未来：{when.isoformat()}", event.event_id)
                    )
                if when not in known_dates:
                    report.violations.append(
                        Violation("fabricated_date", f"日期不在输入数据中：{when.isoformat()}", event.event_id)
                    )
            if start > end:
                report.violations.append(Violation("date_order", "起始时间晚于结束时间", event.event_id))

        if not event.source_ids:
            report.violations.append(Violation("event_without_source", "事件没有来源", event.event_id))

        # Corroboration claims are checked against *independent* sources, not raw source
        # ids: two feeds carrying the same content (HN Algolia + hnrss) are one source,
        # so an event reported by both is not multi-source and must not say it is.
        if event.evidence_level == "multi_source" and event.independent_source_count < 2:
            report.violations.append(
                Violation(
                    "false_multi_source",
                    f"声称多源交叉验证，但独立来源只有 {event.independent_source_count} 个"
                    f"（来源 {event.source_ids}）",
                    event.event_id,
                )
            )
        if event.evidence_level == "single_source" and event.independent_source_count > 1:
            report.violations.append(
                Violation(
                    "wrong_evidence_level",
                    f"有 {event.independent_source_count} 个独立来源却标为单源",
                    event.event_id,
                )
            )
        if not allow_singletons and len(event.member_item_ids) == 1:
            continue

    if not digest.source_coverage.total:
        report.violations.append(Violation("no_coverage", "缺少来源覆盖统计"))

    return report


def check_insight(payload: dict, *, item_ids: list[str]) -> list[Violation]:
    """Validate one model-produced insight before it is trusted.

    The model returns ids, never URLs, so the only things to check are that the ids are
    real, that the three epistemic buckets exist and are separate, and that nothing
    pretends to be a link.
    """
    out: list[Violation] = []
    if not isinstance(payload, dict):
        return [Violation("bad_shape", "模型输出不是对象")]

    for key in ("facts", "inferences", "opinions"):
        if key not in payload:
            out.append(Violation("missing_bucket", f"缺少 {key} 字段"))
        elif not isinstance(payload[key], list):
            out.append(Violation("bad_bucket", f"{key} 不是数组"))

    for bucket in ("facts", "inferences", "opinions", "uncertainties", "key_points"):
        for entry in payload.get(bucket) or []:
            if not isinstance(entry, str):
                continue
            if "http://" in entry or "https://" in entry:
                out.append(
                    Violation("url_in_text", f"模型在正文里写了链接（应由程序回填）：{entry[:80]}")
                )
    return out


def _all_events(digest: Digest) -> list[Event]:
    seen: dict[str, Event] = {}
    for event in [*digest.top_events, *(e for rows in digest.sections.values() for e in rows)]:
        seen[event.event_id] = event
    return list(seen.values())
