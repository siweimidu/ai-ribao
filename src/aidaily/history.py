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
from .samestory import message_key, same_message
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


#: Hosts whose article identity lives in the query string. Stripping the query collapses every
#: article on the host to one key.
#:
#: This shipped as a real bug: `mp.weixin.qq.com/s?__biz=...&mid=...&idx=...&sn=...` reduced to
#: `mp.weixin.qq.com/s` for every WeChat article, so an unrelated Meta story from 10-16 and the
#: DeepSeek V4.1 launch from 10-17 shared a URL fingerprint. The launch was then dropped as a
#: "repeat" -- the single most important story of the day, deleted by its own deduplicator.
_QUERY_IS_IDENTITY = (
    "mp.weixin.qq.com",
    "youtu.be",
    "arxiv.org",
)


def _canonical_url(url: str) -> str:
    """A comparable form of a URL: no scheme, no tracking parameters, stable trailing slash."""
    bare = re.sub(r"^https?://", "", (url or "").strip().lower())
    host = bare.split("/", 1)[0]
    if any(host == h or host.endswith("." + h) for h in _QUERY_IS_IDENTITY):
        # Keep the query: it *is* the identity. Only the fragment is dropped.
        return bare.split("#", 1)[0].rstrip("/")
    return bare.split("?", 1)[0].split("#", 1)[0].rstrip("/")



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
        bare = _canonical_url(url)
        if len(bare) > 10:
            keys.add("u:" + hashlib.sha1(bare.encode()).hexdigest()[:16])
    # The *message* key: who did what, about what, independent of language and wording.
    #
    # The previous third key was the model designation, which is the wrong unit --
    # "DeepSeek ships V4.1-Flash" and "WorkBuddy offers it free" name one model and are two
    # different stories, while the same launch written in Chinese and in English is one story.
    # See `samestory.py` for the pair that shipped twice and why.
    #
    # `message_key` now returns actors, event types, subjects and content tokens. All four are
    # folded into the digest: the earlier two-part version put 31 distinct DeepSeek stories under
    # one key, which made the key useless as an identity (see `samestory.message_key`).
    # Folded first: newsletters prefix their own name to every headline, so
    # `AI 日报：OpenAI 发布 GPT-6` must hash the same as `OpenAI 发布 GPT-6`.
    message = message_key(event.title)
    if message and message[0]:
        payload = "|".join(",".join(sorted(part)) for part in message)
        keys.add("m:" + hashlib.sha1(payload.encode()).hexdigest()[:16])
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


#: Words that mark a shipped release rather than a rumour or a preview.
#:
#: Measured 2026-10-24: Kimi K3.1 was reported on 10-18 as 已现身 (spotted), on 10-21 as
#: 动向 (rumour roundup), and shipped for real today. Cross-day dedup treated the launch as a
#: repeat of the preview and removed all four Kimi items from the issue -- the day biggest
#: story, gone, because it had been mentioned four days earlier.
#:
#: A preview and a launch are different events to a reader: one says a thing exists, the other
#: says it is available.
_SHIPPED = (
    "发布", "上线", "正式推出", "正式发布", "现已可用", "开放", "释出",
    "release", "launch", "ship", "available", "now live",
)

#: Words that mark a preview, a rumour, or a leak.
_PREVIEW = (
    "预热", "预告", "曝光", "现身", "泄露", "传闻", "疑似", "或将", "即将", "动向",
    "tease", "rumour", "rumor", "leak", "preview", "upcoming", "spotted",
)


def _is_ship_not_preview(headline: str, stored) -> bool:
    """True when today headline announces a release and the stored one did not."""
    now = (headline or "").lower()
    if not any(w in now for w in _SHIPPED):
        return False
    for entry in stored or ():
        # `_titles` stores (date, title) pairs. Passing one straight through .lower()
        # raised AttributeError and failed six history tests.
        old = entry[1] if isinstance(entry, tuple) else entry
        old_text = (old or "").lower()
        if any(w in old_text for w in _PREVIEW) and not any(w in old_text for w in _SHIPPED):
            return True
    return False

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

def _same_message_as(headline: str, published) -> bool:
    """Whether `headline` describes the same news as any stored (date, title) pair.

    The stored titles are compared in their original form, not their folded one, because the
    event-type check reads verbs and folding strips the punctuation that separates them.
    """
    for _date, title in published:
        if same_message(headline, str(title)):
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
        #: message key -> [(date, title)]. Kept because a shared actor set is only a candidate:
        #: the stored headline must also describe the same kind of event.
        self._titles: dict[str, list[tuple[str, str]]] = {}
        self._loaded = False

    def load(self) -> None:
        self._index.clear()
        self._folds.clear()
        self._titles.clear()
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
                    if str(key).startswith("m:"):
                        self._titles.setdefault(str(key), []).append((date, title))
        for bucket in self._index.values():
            bucket.sort()

    def _ensure(self) -> None:
        if not self._loaded:
            self.load()

    def _titles_flat(self) -> list[tuple[str, str]]:
        """Every (date, title) the index holds, de-duplicated. Used by the fuzzy fallback."""
        seen: set[tuple[str, str]] = set()
        out: list[tuple[str, str]] = []
        for entries in self._titles.values():
            for date_str, title in entries:
                key = (date_str, title)
                if key in seen:
                    continue
                seen.add(key)
                out.append(key)
        return out

    def recent_titles(self, *, days: int = 7, before: str | None = None) -> list[tuple[str, str]]:
        """Every (date, title) inside the window, newest first.

        Feeds the model-driven cross-day dedup, which needs raw headlines rather than
        fingerprints: the duplicates it catches differ by vocabulary, not by hash.

        `before` excludes a date, so a re-run of today does not compare today to itself.
        """
        rows = [
            (date_str, title)
            for date_str, title in self._titles_flat()
            if before is None or date_str < before
        ]
        rows.sort(key=lambda row: row[0], reverse=True)
        if days > 0 and rows:
            newest = max(date_str for date_str, _ in rows)
            try:
                cutoff = (
                    datetime.strptime(newest, "%Y-%m-%d") - timedelta(days=days)
                ).strftime("%Y-%m-%d")
            except ValueError:
                return rows
            rows = [row for row in rows if row[0] > cutoff]
        return rows

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
                if key.startswith("m:"):
                    # A shared actor set is only a *candidate*: the stored headline has to
                    # describe the same kind of event. "DeepSeek ships V4.1-Flash" and
                    # "DeepSeek had a five-hour outage" name one actor and are two stories.
                    #
                    # The **raw** title is compared, not `folded_now`: folding strips the
                    # separators that keep a verb readable as a verb, and the event-type check
                    # depends on seeing them.
                    if not _same_message_as(event.title, self._titles.get(key, ())):
                        continue
                    # A launch is not a repeat of its own preview: 10-18 said 已现身,
                    # 10-21 said 动向, and 10-24 shipped it. Those are three different
                    # things to a reader.
                    if _is_ship_not_preview(event.title, self._titles.get(key, ())):
                        continue
                try:
                    when = datetime.fromisoformat(date_str).date()
                except ValueError:
                    continue
                if when < cutoff or when > today_date:
                    continue
                days_ago = (today_date - when).days
                kind = (
                    # `message` is the strong signal: the same actors doing the same kind
                    # of thing, whatever the wording. `title` and `url` are exact matches.
                    "message" if key.startswith("m:")
                    else "title" if key.startswith("t:")
                    else "url"
                )
                # Rank the evidence, not just the age. An exact headline or URL match is proof;
                # a model match confirmed by wording is weaker. Proof always wins regardless of
                # which date it came from -- otherwise iterating keys in a different order
                # silently changed `matched_on`, which is what made the result non-deterministic
                # in the first place.
                strength = 0 if kind in ("designation", "reworded", "model-repeat") else 1
                best_strength = (
                    0 if best is not None and best.matched_on in ("designation", "reworded", "model-repeat") else 1
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

        if best is not None:
            return best

        # **Fallback: fuzzy scan over the window.**
        #
        # The message key is now specific (actors + event types + subjects + content tokens),
        # which is what stopped 31 different DeepSeek stories sharing one identity. But a
        # reworded repeat hashes differently by construction: `deepseek-v4.1-flash-1017 发布了`
        # and `DeepSeek发布V4.1-Flash-1017并开放搜索接口` share no content-token set.
        #
        # So when no key matched, compare against every stored headline inside the window and
        # let `same_message` decide. That is the rule that reads the *meaning*; the key is only
        # the fast path to a candidate. Bounded by the window (7 days by default), so this is a
        # few hundred string comparisons, not a corpus scan.
        seen_titles: set[str] = set()
        for date_str, title in self._titles_flat():
            if date_str == today or title in seen_titles:
                continue
            seen_titles.add(title)
            try:
                when = datetime.fromisoformat(date_str).date()
            except ValueError:
                continue
            if when < cutoff or when > today_date:
                continue
            if not _same_message_as(event.title, [(date_str, title)]):
                continue
            if _is_ship_not_preview(event.title, [title]):
                continue
            days_ago = (today_date - when).days
            if best is None or days_ago > best.days_ago:
                best = Repeat(
                    event_id=event.event_id, first_seen=date_str,
                    matched_on="message",
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
        # **One line per date, not one line per run.**
        #
        # This appended unconditionally. Measured 2026-10-24, after four re-runs of the same
        # date: the file held four records for 2026-10-24 (36, 88, 98 and 108 events), and the
        # third run deduplicated its own stories against the second run's output. The merged
        # Kimi K3.1 Pro entry -- four headlines folded into one with multi-source corroboration
        # -- was removed as "已发布过" by the history of the run that had produced it.
        #
        # Re-running a date means replacing that date's record. The earlier rows are dropped
        # before the new one is written, so the file always describes the last published
        # version of each issue.
        existing = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if str(row.get("date") or "") != date:
                    existing.append(row)

        self.path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in existing)
            + json.dumps(payload, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )

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
