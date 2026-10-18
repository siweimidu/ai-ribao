"""Cross-day memory: do not serve yesterday's news as today's.

The digest had no memory of what it had already published. `config.daily.yaml` declares
`dedup.cross_day_window_days: 7`, but **nothing read it** -- the field was dead
configuration, which is worse than an absent feature because it looks implemented.

The consequence is the one every reader notices first: a story that dominated yesterday
reappears at the top today with a new timestamp and no new information. Horizon solves this
with a local BM25 index; daily-briefing keeps a 60-day `history.json` keyed on two fields.

This is the smaller, file-based version of the same idea, and it follows the project's
existing rule for anything doubtful: **demote, never delete.** A repeat is heavily
penalised rather than dropped, so

* a genuinely thin day still has something to print, and
* a story that developed overnight -- new sources, new URLs, a new headline -- can still
  earn its place back, because the penalty is applied to the *match*, not to the story.

The record is append-only JSONL, one line per published event, so the history survives a
checkout of an older commit and can be rebuilt from the archived digests if it is lost.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .designation import designation
from .models import Event

#: Characters stripped before comparing headlines. Punctuation and spacing differ between
#: the same story as reported by two outlets ("GPT-6 released!" vs "GPT-6  released").
_NOISE = re.compile(r"[\s\u3000·・:：,，.。!！?？\"'“”‘’()（）\[\]【】<>《》/\\|—–\-_]+")

#: Words too common to distinguish one AI headline from another. Removed before hashing so
#: "AI 日报：OpenAI 发布 GPT-6" and "OpenAI 发布 GPT-6" collide, as they should.
_FILLER = (
    "ai", "人工智能", "日报", "早报", "晚报", "晨报", "周刊", "周报", "月报",
    "每日", "今日", "今日要闻", "第", "期", "独家", "重磅", "突发", "最新",
)


def _fold(text: str) -> str:
    """Normalise a headline to its comparable core."""
    low = _NOISE.sub("", (text or "").lower())
    for word in _FILLER:
        low = low.replace(word, "")
    return low


def fingerprint(event: Event) -> set[str]:
    """Two keys per event, as daily-briefing does: a title key and a URL key.

    Either is enough to recognise a repeat. The title catches the same story re-reported by
    a different outlet; the URL catches the same link resurfacing under a rewritten headline.
    A single key would miss one of those.
    """
    keys: set[str] = set()
    folded = _fold(event.title)
    if len(folded) >= 6:
        keys.add("t:" + hashlib.sha1(folded.encode()).hexdigest()[:16])
    for url in event.all_urls or ():
        # Canonical form: strip the scheme, the query and a trailing slash, so tracking
        # parameters and http/https do not read as different pages.
        bare = re.sub(r"^https?://", "", (url or "").strip().lower())
        bare = bare.split("?", 1)[0].split("#", 1)[0].rstrip("/")
        if len(bare) > 10:
            keys.add("u:" + hashlib.sha1(bare.encode()).hexdigest()[:16])
    # Not hashed: the key is already a short normalised product name, and keeping it legible
    # makes the history file readable when diagnosing a repeat.
    model = designation(event.title)
    if model:
        keys.add("d:" + model)
    return keys


@dataclass
class Repeat:
    event_id: str
    first_seen: str
    matched_on: str
    days_ago: int


#: Two headlines about one model above this similarity describe the same event worded
#: differently. See the call site in `find_repeat` for the measured pairs this sits between.
NEAR_MATCH_RATIO = 0.80


def _is_near_match(headline: str, published) -> bool:
    """Whether `headline` restates one of `published` in slightly different words."""
    from difflib import SequenceMatcher

    for other in published:
        longer = max(len(headline), len(other))
        if not longer:
            continue
        # Cheap rejection first: headlines whose lengths differ by more than half cannot reach
        # the threshold, and the comparison below is O(n*m).
        if abs(len(headline) - len(other)) > longer * 0.5:
            continue
        if SequenceMatcher(None, headline, other).ratio() >= NEAR_MATCH_RATIO:
            return True
    return False

class PublishedHistory:
    """Append-only record of what each issue published, and the lookup over it."""

    def __init__(self, path: Path, window_days: int = 7) -> None:
        self.path = path
        self.window_days = window_days
        #: fingerprint -> [(date, title)], oldest first.
        #:
        #: Every date is kept, not just one. Keeping only the newest loses "this has been
        #: running all week"; keeping only the oldest breaks the window check -- a story
        #: first seen 20 days ago and again yesterday would look like it was last published
        #: 20 days ago and so fall outside the window, when it is exactly the repeat the
        #: window exists to catch.
        self._index: dict[str, list[tuple[str, str]]] = {}
        #: date -> folded headlines published that day. Used for the near-match check, which
        #: the exact hashes cannot serve: one inserted word defeats a hash.
        self._folds: dict[str, list[str]] = {}
        self._loaded = False

    def load(self) -> None:
        self._index.clear()
        self._folds.clear()
        self._loaded = True
        if not self.path.exists():
            return
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            date = str(row.get("date") or "")
            if not date:
                continue
            # Current format: one record per issue holding every event. The earlier
            # per-event format is still read, because a file written by the previous version
            # may already be committed.
            if "events" in row:
                entries = [
                    (str(e.get("id") or ""), str(e.get("title") or ""), e.get("keys") or [])
                    for e in row.get("events") or []
                    if isinstance(e, dict)
                ]
            else:
                entries = [(str(row.get("event_id") or ""), str(row.get("title") or ""),
                            row.get("keys") or [])]
            if "events" in row:
                for entry in row.get("events") or []:
                    if isinstance(entry, dict) and entry.get("fold"):
                        self._folds.setdefault(date, []).append(str(entry["fold"]))
            for _event_id, title, keys in entries:
                for key in keys:
                    bucket = self._index.setdefault(str(key), [])
                    if not any(d == date for d, _ in bucket):
                        bucket.append((date, title))
        for bucket in self._index.values():
            bucket.sort()

    def _ensure(self) -> None:
        if not self._loaded:
            self.load()

    def find_repeat(self, event: Event, *, today: str, now: datetime) -> Repeat | None:
        """Whether this event was published inside the window, and how long it has run.

        `days_ago` is measured from the **earliest** sighting inside the window, because the
        useful fact is "this has been running for N days", not "this also appeared
        yesterday". `first_seen` is that same date.
        """
        self._ensure()
        keys = fingerprint(event)
        if not keys:
            return None

        try:
            today_date = datetime.fromisoformat(today).date()
        except ValueError:
            return None
        cutoff = today_date - timedelta(days=self.window_days)

        folded_now = _fold(event.title)
        best: Repeat | None = None
        # Sorted, and `>` rather than `>=` when comparing: with both keys matching the same
        # date, whichever a `set` happened to yield last used to win, so `matched_on` varied
        # between runs on identical input. A title match is the more informative report --
        # it means the story was re-reported, not merely relinked -- so it wins ties.
        for key in sorted(keys):
            for date_str, _title in self._index.get(key, ()):
                if date_str == today:
                    # Same day: a re-trigger of today's own issue, not cross-day repetition.
                    continue
                if key.startswith("d:"):
                    # A designation alone only says "this model appeared before", which is not
                    # enough to prove a repeat: "Gemini 4 Argon 机器人模型发布" and "Gemini 4
                    # Argon 在 ARC-AGI-3 获 97.5%" are different events on the same day. Prove
                    # it by comparing the wording, and only then report a repeat.
                    if not _is_near_match(folded_now, self._folds.get(date_str, ())):
                        continue
                try:
                    when = datetime.fromisoformat(date_str).date()
                except ValueError:
                    continue
                if when < cutoff or when > today_date:
                    continue
                days_ago = (today_date - when).days
                kind = (
                    # Reaching here through `d:` already means the wording was compared and
                    # matched, so this is a proven repeat with a weaker trail than an exact
                    # hash -- reported as such rather than as "designation", which would tell
                    # the caller to demote it when the evidence says otherwise.
                    "reworded" if key.startswith("d:")
                    else "title" if key.startswith("t:")
                    else "url"
                )
                # Rank the evidence, not just the age. An exact headline or URL match is proof;
                # a model match confirmed by wording is weaker. Proof always wins regardless of
                # which date it came from -- otherwise iterating keys in a different order
                # silently changed `matched_on`, which is what made the result non-deterministic
                # in the first place.
                strength = 0 if kind in ("designation", "reworded") else 1
                best_strength = (
                    0 if best is not None and best.matched_on in ("designation", "reworded") else 1
                )
                if (
                    best is None
                    or strength > best_strength
                    or (strength == best_strength and days_ago > best.days_ago)
                ):
                    best = Repeat(
                        event_id=event.event_id, first_seen=date_str,
                        matched_on=kind,
                        days_ago=days_ago,
                    )
        return best

    def record(self, events: list[Event], *, date: str) -> int:
        """Append one issue's fingerprints. Returns how many events were written.

        **One line per issue**, not per event. The workflow commits `data/`, so the file
        becomes repository history: at sixty events times roughly two and a half keys, a
        line per event is ~150 lines and ~18 KB a day, or 6 MB a year for information that
        is a few hundred fingerprints. One record per issue is 365 lines a year.
        """
        if not events:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "date": date,
            "events": [
                {"id": e.event_id, "title": e.title[:200], "keys": sorted(fingerprint(e)),
                 "fold": _fold(e.title)[:160]}
                for e in events
            ],
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

        # Keep the in-memory view consistent so a second call in the same run sees them.
        for row in payload["events"]:
            for key in row["keys"]:
                bucket = self._index.setdefault(key, [])
                if not any(d == date for d, _ in bucket):
                    bucket.append((date, row["title"]))
                    bucket.sort()
        return len(payload["events"])

    def rebuild_from_archives(self, digests_dir: Path) -> int:
        """Rebuild the index from `data/digests/*.json` when the history is missing.

        The archived issues are the authoritative record of what was published; the history
        file is a performance cache over them. Losing it must not lose the dedup, so this
        regenerates it rather than starting from empty and re-publishing old news.
        """
        rows: list[tuple[str, Event]] = []
        for path in sorted(digests_dir.glob("????-??-??.json")):
            date = path.stem
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                events = [Event.model_validate(e) for e in payload["digest"]["top_events"]]
            except Exception:  # noqa: BLE001
                continue
            # Record the title the reader actually saw. The archived `insights` hold the
            # Chinese headline the page rendered while `event.title` keeps the raw source
            # wording; the displayed one is what a repeat repeats. On 2026-10-17 these differed
            # ("Google AI Studio 向 Pro 订阅用户开放 Gemini 4 Argon" against the displayed
            # "Gemini 4 Argon 向 Google AI Pro 开放") and only the second repeats 10-16.
            insights = payload.get("insights") or {}
            for e in events:
                shown = (insights.get(e.event_id) or {}).get("title")
                if shown:
                    e = e.model_copy(update={"title": shown})
                rows.append((date, e))

        if not rows:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        by_date: dict[str, list[Event]] = {}
        for date, event in rows:
            by_date.setdefault(date, []).append(event)
        with self.path.open("w", encoding="utf-8") as handle:
            for date in sorted(by_date):
                handle.write(json.dumps({
                    "date": date,
                    "events": [
                        {"id": e.event_id, "title": e.title[:200],
                         "keys": sorted(fingerprint(e)),
                         "fold": _fold(e.title)[:160]}
                        for e in by_date[date]
                    ],
                }, ensure_ascii=False) + "\n")
        self.load()
        return len(rows)
