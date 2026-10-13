"""Fact checking, rendering, and the text hygiene that feeds both."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aidaily.analyze import EventInsight
from aidaily.factcheck import check_digest, check_insight
from aidaily.models import Digest, Event, NormalizedItem, SourceCoverage
from aidaily.normalize import strip_html, strip_text_urls
from aidaily.render import render_brief, render_deep, render_json_feed

NOW = datetime(2026, 10, 14, 2, 0, tzinfo=timezone.utc)


@pytest.fixture
def item():
    return NormalizedItem(
        item_id="i1", source_id="rss:test", title="A story",
        title_norm="astory", url="https://example.com/a",
        published_at=NOW, fetched_at=NOW, first_seen_at=NOW, updated_at=NOW,
        summary="summary", content_text="body", content_sha256="h", simhash=1,
    )


def make_event(**kw) -> Event:
    base = dict(
        event_id="e1", title="A story", member_item_ids=["i1"], primary_item_id="i1",
        source_ids=["rss:test"], all_urls=["https://example.com/a"],
        independent_source_count=1,
        first_seen_at=NOW, last_updated_at=NOW,
        published_range=(NOW, NOW), evidence_level="single_source",
    )
    base.update(kw)
    return Event(**base)


def make_digest(event: Event, **kw) -> Digest:
    base = dict(
        date="2026-10-14", kind="deep", generated_at=NOW,
        window_start=NOW - timedelta(hours=26), window_end=NOW,
        top_events=[event], source_coverage=SourceCoverage(total=10, active=3),
    )
    base.update(kw)
    return Digest(**base)


# =============================== text hygiene ====================================
def test_strip_html_removes_tags_and_entities() -> None:
    raw = '<p>Article URL: <a href="https://x.example/a">link</a></p><p>Points: 308</p>'
    got = strip_html(raw)
    assert "<" not in got and "&" not in got
    assert "Article URL" in got and "Points: 308" in got


def test_strip_html_turns_block_tags_into_newlines() -> None:
    assert "\n" in strip_html("<p>one</p><p>two</p>")


def test_strip_text_urls_removes_bare_links() -> None:
    """Regression: aihot summaries embedded their own links, which bypassed the
    'every URL is one we recorded' guarantee."""
    got = strip_text_urls("提示词已开放。在这里 Remix: https://app.pixverse.ai/video/123?utm_source=X")
    assert "http" not in got
    assert "提示词已开放" in got


def test_strip_text_urls_drops_furniture_lines() -> None:
    assert strip_text_urls("via AIHOT · https://aihot.news/x") == ""
    assert strip_text_urls("🔗 阅读原文") == ""
    assert strip_text_urls("Read more →") == ""


def test_strip_text_urls_keeps_real_content() -> None:
    assert strip_text_urls("OpenAI released a model today.") == "OpenAI released a model today."


# =============================== fact check ======================================
def test_clean_digest_passes(item) -> None:
    event = make_event()
    report = check_digest(make_digest(event), [item])
    assert report.ok, report.summary()


def test_fabricated_url_is_caught(item) -> None:
    """The single most important check: a link the input never contained."""
    event = make_event(all_urls=["https://example.com/a", "https://invented.example/b"])
    report = check_digest(make_digest(event), [item])

    assert not report.ok
    assert "fabricated_url" in report.summary()["by_kind"]


def test_fabricated_date_is_caught(item) -> None:
    other = NOW - timedelta(days=30)
    event = make_event(published_range=(other, other))
    report = check_digest(make_digest(event), [item])

    assert not report.ok
    assert "fabricated_date" in report.summary()["by_kind"]


def test_future_date_is_caught(item) -> None:
    ahead = NOW + timedelta(days=5)
    event = make_event(published_range=(ahead, ahead))
    report = check_digest(make_digest(event), [item])

    assert "future_date" in report.summary()["by_kind"]


def test_event_without_any_url_is_caught(item) -> None:
    report = check_digest(make_digest(make_event(all_urls=[])), [item])
    assert "event_without_url" in report.summary()["by_kind"]


def test_false_multi_source_is_caught(item) -> None:
    """Claiming corroboration with one independent source is a lie to the reader."""
    event = make_event(
        source_ids=["rss:a", "rss:b"], independent_source_count=1,
        evidence_level="multi_source",
    )
    report = check_digest(make_digest(event), [item])

    assert "false_multi_source" in report.summary()["by_kind"]


def test_understated_multi_source_is_caught(item) -> None:
    event = make_event(
        source_ids=["rss:a", "rss:b"], independent_source_count=2,
        evidence_level="single_source",
    )
    report = check_digest(make_digest(event), [item])
    assert "wrong_evidence_level" in report.summary()["by_kind"]


def test_unknown_member_id_is_caught(item) -> None:
    report = check_digest(make_digest(make_event(member_item_ids=["i1", "ghost"])), [item])
    assert "unknown_member" in report.summary()["by_kind"]


# =============================== insight guard ===================================
def test_insight_requires_all_three_buckets() -> None:
    violations = check_insight({"facts": ["a"]}, item_ids=["i1"])
    kinds = {v.kind for v in violations}
    assert "missing_bucket" in kinds


def test_insight_rejects_urls_in_prose() -> None:
    violations = check_insight(
        {"facts": ["见 https://invented.example/x"], "inferences": [], "opinions": []},
        item_ids=["i1"],
    )
    assert any(v.kind == "url_in_text" for v in violations)


def test_insight_accepts_clean_payload() -> None:
    assert check_insight(
        {"facts": ["f"], "inferences": ["i"], "opinions": ["o"], "uncertainties": ["u"]},
        item_ids=["i1"],
    ) == []


# =============================== rendering =======================================
def _insight(event_id: str = "e1") -> EventInsight:
    return EventInsight(
        event_id=event_id, title="Headline", facts=["fact one"], inferences=["inference one"],
        opinions=[], uncertainties=["uncertain one"], key_points=["point"],
    )


def test_brief_contains_every_source_link(item) -> None:
    event = make_event(all_urls=["https://example.com/a", "https://other.example/b"],
                       source_ids=["rss:a", "rss:b"], independent_source_count=2,
                       evidence_level="multi_source")
    out = render_brief(make_digest(event), {"e1": _insight()}, {"i1": item})

    assert "https://example.com/a" in out
    assert "https://other.example/b" in out
    assert "多源" in out


def test_deep_labels_the_epistemic_buckets(item) -> None:
    out = render_deep(make_digest(make_event()), {"e1": _insight()}, {"i1": item})

    for label in ("**事实**", "**推断**", "**不确定**"):
        assert label in out


def test_deep_reports_coverage_honestly(item) -> None:
    digest = make_digest(make_event(), source_coverage=SourceCoverage(total=80, active=17, failed=9, skipped=54))
    out = render_deep(digest, {}, {"i1": item})

    assert "80" in out and "17" in out and "9" in out and "54" in out


def test_deep_labels_rule_based_entries(item) -> None:
    insight = EventInsight(event_id="e1", title="T", facts=["f"], rule_based=True)
    out = render_deep(make_digest(make_event()), {"e1": insight}, {"i1": item})
    assert "未调用大模型" in out


def test_json_feed_is_valid_json_feed(item) -> None:
    out = render_json_feed(make_digest(make_event()), {}, site_url="https://site.example")
    import json

    doc = json.loads(out)
    assert doc["version"] == "https://jsonfeed.org/version/1.1"
    assert doc["items"][0]["url"] == "https://example.com/a"
    assert doc["items"][0]["_ai_daily"]["source_ids"] == ["rss:test"]


def test_warnings_are_rendered(item) -> None:
    digest = make_digest(make_event(), warnings=["juya 当日版未发布，本期使用 T-1 版本"])
    assert "T-1" in render_brief(digest, {}, {"i1": item})
    assert "T-1" in render_deep(digest, {}, {"i1": item})
