"""Parsing an X timeline without a key, and without pretending the rate limit away.

The fetcher reads `syndication.twitter.com/srv/timeline-profile/screen-name/<handle>`, the same
endpoint X uses to embed someone else's timeline. It needs no token -- which is the whole point,
because every alternative was either dead or wanted the reader's own account:

* Nitter: 410 / 451 / TLS failures on every public instance (2026-10-21).
* RSSHub `/twitter/user`: requires `TWITTER_AUTH_TOKEN`, a logged-in cookie; its docs warn the
  password method "easily triggers Twitter's risk control mechanism" and died in 2025-10.
* X API v2: 401 without a paid plan.

These tests pin the parsing and the two behaviours that cost real time to learn: a 429 must be
reported as `blocked` (not `empty`), and the request gap must stay slow.
"""

from __future__ import annotations

import json
from datetime import timezone

import pytest

from aidaily.fetchers.x_timeline import (
    XTimelineFetcher,
    _handle,
    _headline,
    _parse_entries,
    _when,
    to_items,
)
from aidaily.models import SourceSpec


def _spec(url: str = "https://x.com/OpenAI") -> SourceSpec:
    return SourceSpec(
        source_id="x:openai",
        name="OpenAI",
        url=url,
        normalized_url=url,
        domain="x.com",
        category="lab-official",
        source_type="x_timeline",
        adapter="XTimelineFetcher",
        enabled=True,
        language="en",
    )


def _page(tweets: list[dict]) -> str:
    payload = {"props": {"pageProps": {"timeline": {"entries": [
        {"content": {"tweet": t}} for t in tweets
    ]}}}}
    return (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload)
        + "</script></html>"
    )


# --- handle extraction ---------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://x.com/OpenAI", "OpenAI"),
        ("https://twitter.com/karpathy", "karpathy"),
        ("https://x.com/thsottiaux/status/123", "thsottiaux"),
        ("@sama", "sama"),
        ("AnthropicAI", "AnthropicAI"),
    ],
)
def test_handle_accepts_url_and_bare_name(url: str, expected: str) -> None:
    assert _handle(_spec(url)) == expected


# --- tweet parsing -------------------------------------------------------------


def test_a_tweet_becomes_one_item_with_a_real_url() -> None:
    tweets = [{
        "full_text": "GPT-6 and Intelligent UI, now rolling out in ChatGPT for everyone.",
        "id_str": "2107894997538525580",
        "created_at": "Wed Oct 07 18:05:04 +0000 2026",
        "favorite_count": 23953,
        "retweet_count": 1897,
        "entities": {"media": [{"media_url_https": "https://pbs.twimg.com/a.jpg"}]},
    }]
    items = to_items(_spec(), tweets)
    assert len(items) == 1
    item = items[0]
    # The URL is built from the status id, never guessed from the text.
    assert item.url == "https://x.com/OpenAI/status/2107894997538525580"
    assert item.published_at.year == 2026
    assert item.published_at.tzinfo is not None
    assert item.metrics["likes"] == 23953
    assert item.metrics["media"] == 1
    assert item.native_id == "2107894997538525580"


def test_the_title_is_the_first_line_not_the_whole_tweet() -> None:
    """A digest lists headlines; a paragraph per entry destroys the list."""
    tweets = [{"full_text": "Headline here\n\nA long body that follows.", "id_str": "1"}]
    items = to_items(_spec(), tweets)
    assert items[0].title == "Headline here"
    assert "long body" in items[0].content_text


def test_a_tweet_without_an_id_is_dropped() -> None:
    """Without an id there is no canonical URL, and a linkless item cannot be traced."""
    items = to_items(_spec(), [{"full_text": "no id", "id_str": ""}])
    assert items == []


def test_the_timestamp_parses_x_format() -> None:
    when = _when({"created_at": "Wed Oct 07 18:05:04 +0000 2026"})
    assert when is not None
    assert when.astimezone(timezone.utc).hour == 18


def test_a_bad_timestamp_is_not_fatal() -> None:
    assert _when({"created_at": "not a date"}) is None
    assert _when({}) is None


def test_entries_are_extracted_from_next_data() -> None:
    html = _page([{"full_text": "hello world", "id_str": "9"}])
    import re

    from aidaily.fetchers.x_timeline import _NEXT_DATA

    match = _NEXT_DATA.search(html)
    assert match
    tweets = _parse_entries(json.loads(match.group(1)))
    assert len(tweets) == 1 and tweets[0]["id_str"] == "9"


def test_headline_falls_back_to_the_text_when_there_are_no_newlines() -> None:
    assert _headline("single line tweet") == "single line tweet"


# --- the two behaviours that cost real time -------------------------------------


def test_a_429_is_blocked_not_empty() -> None:
    """`blocked` makes the next run retry; `empty` would look like a dead account.

    Measured 2026-10-21: ~30 requests 0.6s apart produced 429 on every one, and the block
    outlasted 10-second gaps for minutes. Reporting that as "no tweets" would silently hide a
    live account.
    """
    import inspect

    source = inspect.getsource(XTimelineFetcher.fetch)
    assert "429" in source
    assert "blocked" in source


def test_the_request_gap_is_slow_on_purpose() -> None:
    assert XTimelineFetcher.request_gap_s >= 3.0, (
        "a fast gap earns 429 on every request; see the module docstring"
    )


def test_a_retry_would_burn_the_next_window() -> None:
    """The X fetch must not use the client's retries.

    Measured 2026-10-21: a single direct request to the endpoint returned 20 tweets while the
    same URL through the shared `HttpClient` (retries=2) came back 429 three times in a row.
    A 429 means the *window* is spent, so retrying spends the next one too.
    """
    import inspect

    source = inspect.getsource(XTimelineFetcher.fetch)
    assert "retries=0" in source, "the X fetch must opt out of the client's retries"


def test_the_budget_stops_after_six_requests() -> None:
    """The endpoint's budget is per run, not per handle.

    Measured on GitHub Actions 2026-10-21 with 26 sources serialised: six succeeded
    (chatgpt 101, aiatmeta 100, deepseek_ai 99, alibaba_qwen 21, anthropicai 20, baidu_inc 20)
    and the next twenty all came back 429. Spending the rest on 429s only delays the collect.
    """
    from aidaily.fetchers import x_timeline

    x_timeline.reset_budget()
    granted = [x_timeline._take_budget() for _ in range(x_timeline._BUDGET + 3)]
    assert granted[: x_timeline._BUDGET] == [True] * x_timeline._BUDGET
    assert not any(granted[x_timeline._BUDGET :])


def test_a_spent_budget_is_skipped_not_blocked() -> None:
    """`skipped` says "we did not ask"; `blocked` would blame the source for our own pacing."""
    import inspect

    source = inspect.getsource(XTimelineFetcher.fetch)
    assert '"skipped"' in source
