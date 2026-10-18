"""Cross-day memory: the digest must not serve yesterday's news as today's.

`dedup.cross_day_window_days: 7` was declared in `config/daily.yaml` and read by **nothing**
-- dead configuration that looked like a working feature. The symptom is the one a reader
notices first: a story that led yesterday's issue leads today's with a new timestamp and no
new information.

The design choice under test is **demote, never delete**, which is the same rule the source
registry follows. A hard drop would empty a quiet day and would also discard a story that
genuinely developed overnight.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aidaily.history import PublishedHistory, fingerprint
from aidaily.models import Event

NOW = datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)


def make_event(
    event_id: str = "e1",
    title: str = "OpenAI releases GPT-6",
    urls: tuple[str, ...] = ("https://example.com/a",),
) -> Event:
    return Event(
        event_id=event_id, title=title, member_item_ids=[f"i-{event_id}"],
        primary_item_id=f"i-{event_id}", source_ids=["rss:s"], all_urls=list(urls),
        independent_source_count=2, first_seen_at=NOW - timedelta(hours=2),
        last_updated_at=NOW, published_range=(NOW - timedelta(hours=2), NOW),
        evidence_level="multi_source",
    )


# =============================== fingerprints ====================================
def test_fingerprint_carries_a_title_key_and_a_url_key() -> None:
    """Two keys, as daily-briefing does: neither alone catches every repeat.

    The title key catches the same story re-reported by a different outlet; the URL key
    catches the same link resurfacing under a rewritten headline.
    """
    keys = fingerprint(make_event())
    assert sum(1 for k in keys if k.startswith("t:")) == 1
    assert sum(1 for k in keys if k.startswith("u:")) == 1


def test_fingerprint_ignores_url_noise() -> None:
    """http/https, a trailing slash and tracking parameters are one page, not three."""
    a = fingerprint(make_event(urls=("https://example.com/story",)))
    b = fingerprint(make_event(urls=("http://example.com/story/",)))
    c = fingerprint(make_event(urls=("https://example.com/story?utm_source=x",)))
    assert a == b == c


def test_fingerprint_folds_editorial_prefixes() -> None:
    """`AI 日报：OpenAI 发布 GPT-6` and `OpenAI 发布 GPT-6` are the same story.

    Newsletters prefix their own name to every headline; without folding, a story is new
    every time a different letter carries it.
    """
    plain = fingerprint(make_event(title="OpenAI 发布 GPT-6", urls=()))
    prefixed = fingerprint(make_event(title="AI 日报：OpenAI 发布 GPT-6", urls=()))
    assert plain == prefixed


def test_fingerprint_of_a_very_short_title_is_empty() -> None:
    """`AI` or `日报` alone would match everything, so nothing is hashed from them."""
    assert fingerprint(make_event(title="AI", urls=())) == set()
    assert fingerprint(make_event(title="日报", urls=())) == set()


# =============================== repeat detection ================================
def test_a_story_from_yesterday_is_recognised(tmp_path: Path) -> None:
    history = PublishedHistory(tmp_path / "h.jsonl", window_days=7)
    history.record([make_event(title="OpenAI releases GPT-6")], date="2026-10-14")

    repeat = history.find_repeat(
        make_event(title="OpenAI releases GPT-6"), today="2026-10-15", now=NOW
    )
    assert repeat is not None
    assert repeat.first_seen == "2026-10-14"
    assert repeat.days_ago == 1
    # `message` rather than `title`: the message identity (same actors, same event type)
    # now recognises this before the exact-hash fallback is reached. Both are proof; the
    # assertion is about recognising the repeat, not about which key fired first.
    assert repeat.matched_on in {"message", "title"}


def test_the_same_day_is_not_a_cross_day_repeat(tmp_path: Path) -> None:
    """Re-triggering today's own issue must not demote today's content.

    The gate compares against what was last published, and a same-day re-run produces a
    different digest as new items arrive. Treating that as repetition would penalise the
    digest's own headline.
    """
    history = PublishedHistory(tmp_path / "h.jsonl", window_days=7)
    history.record([make_event(title="OpenAI releases GPT-6")], date="2026-10-15")
    assert history.find_repeat(
        make_event(title="OpenAI releases GPT-6"), today="2026-10-15", now=NOW
    ) is None


def test_a_story_outside_the_window_is_not_a_repeat(tmp_path: Path) -> None:
    history = PublishedHistory(tmp_path / "h.jsonl", window_days=7)
    history.record([make_event(title="OpenAI releases GPT-6")], date="2026-10-01")
    assert history.find_repeat(
        make_event(title="OpenAI releases GPT-6"), today="2026-10-15", now=NOW
    ) is None


def test_the_oldest_match_is_reported(tmp_path: Path) -> None:
    """A story recurring all week is a week-old repeat, not yesterday's."""
    history = PublishedHistory(tmp_path / "h.jsonl", window_days=7)
    history.record([make_event(title="OpenAI releases GPT-6")], date="2026-10-10")
    history.record([make_event(title="OpenAI releases GPT-6")], date="2026-10-14")

    repeat = history.find_repeat(
        make_event(title="OpenAI releases GPT-6"), today="2026-10-15", now=NOW
    )
    assert repeat is not None
    assert repeat.days_ago == 5


def test_a_rewritten_headline_is_caught_by_the_url(tmp_path: Path) -> None:
    history = PublishedHistory(tmp_path / "h.jsonl", window_days=7)
    history.record(
        [make_event(title="Google ships Gemini 4 Argon", urls=("https://ex.com/argon",))],
        date="2026-10-14",
    )
    repeat = history.find_repeat(
        make_event(title="Gemini 4 Argon is here", urls=("https://ex.com/argon",)),
        today="2026-10-15", now=NOW,
    )
    assert repeat is not None
    # Same reasoning: the shared URL still proves it, but the message identity usually
    # fires first now.
    assert repeat.matched_on in {"message", "url"}


def test_an_unrelated_story_is_not_a_repeat(tmp_path: Path) -> None:
    history = PublishedHistory(tmp_path / "h.jsonl", window_days=7)
    history.record([make_event(title="OpenAI releases GPT-6")], date="2026-10-14")
    assert history.find_repeat(
        make_event(title="Nvidia announces earnings", urls=("https://ex.com/nv",)),
        today="2026-10-15", now=NOW,
    ) is None


# =============================== durability ======================================
def test_history_survives_a_reload(tmp_path: Path) -> None:
    path = tmp_path / "h.jsonl"
    first = PublishedHistory(path, window_days=7)
    first.record([make_event()], date="2026-10-14")

    second = PublishedHistory(path, window_days=7)
    second.load()
    assert second.find_repeat(make_event(), today="2026-10-15", now=NOW) is not None


def test_a_corrupt_line_does_not_lose_the_rest(tmp_path: Path) -> None:
    """Append-only means a truncated write must cost one line, not the whole memory."""
    path = tmp_path / "h.jsonl"
    history = PublishedHistory(path, window_days=7)
    history.record([make_event(title="OpenAI releases GPT-6")], date="2026-10-14")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")

    reloaded = PublishedHistory(path, window_days=7)
    reloaded.load()
    assert reloaded.find_repeat(
        make_event(title="OpenAI releases GPT-6"), today="2026-10-15", now=NOW
    ) is not None


def test_history_rebuilds_from_the_archive(tmp_path: Path) -> None:
    """The archive is authoritative; the history file is only a cache over it.

    Losing it must not lose the dedup, or the digest would silently re-publish a week of
    old news the moment the cache went missing.
    """
    digests = tmp_path / "digests"
    digests.mkdir()
    event = make_event(title="OpenAI releases GPT-6")
    (digests / "2026-10-14.json").write_text(
        json.dumps({"digest": {"top_events": [json.loads(event.model_dump_json())]}}),
        encoding="utf-8",
    )

    history = PublishedHistory(tmp_path / "h.jsonl", window_days=7)
    history.load()
    assert history.find_repeat(
        make_event(title="OpenAI releases GPT-6"), today="2026-10-15", now=NOW
    ) is None, "nothing recorded yet"

    rebuilt = history.rebuild_from_archives(digests)
    assert rebuilt == 1
    assert history.find_repeat(
        make_event(title="OpenAI releases GPT-6"), today="2026-10-15", now=NOW
    ) is not None
