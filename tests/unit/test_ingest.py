"""Ingest tests: raw item -> normalized item."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from aidaily.ingest import compute_age_bucket, detect_language, item_id_for, normalize_raw
from aidaily.models import RawItem, SourceSpec

NOW = datetime(2026, 10, 14, 2, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 14)


@pytest.fixture
def spec():
    return SourceSpec(
        source_id="rss:example", name="example", url="https://example.com/feed.xml",
        normalized_url="https://example.com/feed.xml", domain="example.com",
        category="media", source_type="rss", adapter="RssFetcher",
        found_in=["repo:file#key"], repositories=["repo"],
    )


# --- language --------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("智谱发布法律模型 GLM-Legal，开放测试申请", "zh"),
        ("OpenAI announced a new reasoning model today", "en"),
        ("", None),
        ("12345 !!! ---", None),
    ],
)
def test_detect_language(text: str, expected: str | None) -> None:
    assert detect_language(text) == expected


def test_detect_language_ignores_brand_names_in_english_text() -> None:
    """A mostly-English item mentioning 机器之心 is still English."""
    text = ("OpenAI shipped a new model. " * 20) + "机器之心"
    assert detect_language(text) == "en"


# --- age buckets -----------------------------------------------------------------
def test_window_source_is_labelled_today_window() -> None:
    """GitHub Trending's 'today' is a star delta, not a date -- label it, do not fake it."""
    assert compute_age_bucket(None, TODAY, window_source=True) == "today_window"


def test_missing_date_is_unknown_not_today() -> None:
    assert compute_age_bucket(None, TODAY, window_source=False) == "unknown"


@pytest.mark.parametrize(
    "published,expected",
    [
        (datetime(2026, 10, 14, 1, 0, tzinfo=timezone.utc), "today"),
        (datetime(2026, 10, 13, 1, 0, tzinfo=timezone.utc), "past_72h"),
        (datetime(2026, 10, 10, 1, 0, tzinfo=timezone.utc), "older"),
    ],
)
def test_age_buckets(published: datetime, expected: str) -> None:
    assert compute_age_bucket(published, TODAY, window_source=False) == expected


def test_future_date_is_treated_as_today() -> None:
    """Feeds with a wrong timezone can look slightly ahead; that must not crash or mislabel."""
    assert (
        compute_age_bucket(
            datetime(2026, 10, 15, 0, 30, tzinfo=timezone.utc), TODAY, window_source=False
        )
        == "today"
    )


# --- normalize_raw ---------------------------------------------------------------
def test_missing_date_stays_missing_after_normalization(spec) -> None:
    raw = RawItem(source_id=spec.source_id, title="No date", url="https://example.com/a")
    item = normalize_raw(raw, spec, NOW)

    assert item.published_at is None
    assert item.age_bucket == "unknown"
    assert item.fetched_at == NOW


def test_normalization_fills_fingerprints(spec) -> None:
    raw = RawItem(
        source_id=spec.source_id, title="OpenAI ships a model", url="https://example.com/a",
        published_at=NOW, summary="summary text", content_text="body text here",
    )
    item = normalize_raw(raw, spec, NOW)

    assert item.title_norm == "openaishipsamodel"
    assert item.content_sha256
    assert item.simhash != 0
    assert item.age_bucket == "today"
    assert item.first_seen_at == NOW


def test_item_id_is_stable_across_url_changes_when_native_id_exists(spec) -> None:
    """A feed that re-issues an item under a new URL must still map to one record."""
    a = RawItem(source_id=spec.source_id, title="T", url="https://example.com/a", native_id="guid-1")
    b = RawItem(source_id=spec.source_id, title="T", url="https://example.com/b", native_id="guid-1")
    c = RawItem(source_id=spec.source_id, title="T", url="https://example.com/b", native_id="guid-2")

    assert item_id_for(spec, a) == item_id_for(spec, b)
    assert item_id_for(spec, a) != item_id_for(spec, c)


def test_item_id_falls_back_to_normalized_url(spec) -> None:
    """Tracking params differ per fetch; identity must not."""
    a = RawItem(source_id=spec.source_id, title="T", url="https://example.com/a?utm_source=rss")
    b = RawItem(source_id=spec.source_id, title="T", url="https://example.com/a")
    assert item_id_for(spec, a) == item_id_for(spec, b)


def test_language_falls_back_to_detection(spec) -> None:
    raw = RawItem(source_id=spec.source_id, title="智谱发布法律模型", url="https://example.com/a")
    assert normalize_raw(raw, spec, NOW).language == "zh"


def test_explicit_language_from_source_wins(spec) -> None:
    spec2 = spec.model_copy(update={"language": "en"})
    raw = RawItem(source_id=spec2.source_id, title="智谱发布法律模型", url="https://example.com/a")
    assert normalize_raw(raw, spec2, NOW).language == "en"
