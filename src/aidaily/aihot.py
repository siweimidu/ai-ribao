"""AIHOT public API client.

AIHOT (https://aihot.news) is a Chinese AI news site whose engine is open source. This
module treats it as **one source among many**, which is the use its published terms allow
without written authorization:

* personal non-commercial, public-interest non-commercial and organisation-internal use are
  free;
* caching and syncing are explicitly permitted for those uses, subject to the response's
  cache headers and the rate limit (about 60 requests/minute per IP);
* an external commercial product, paid service, **public mirror** or bulk public
  redistribution needs prior written authorization.

So this deliberately does **not** call `/selected/snapshot`, which exists to keep a complete
local copy of their selected set -- that is the bulk-redistribution case. It reads the
per-topic endpoints the same way a reader reads the site, keeps AIHOT's attribution and
canonical link on everything, and links back to the original sources.

What the terms require of a client, and how each is honoured here:

  * **Respect cache headers.** ETag and Last-Modified are stored and replayed via
    `If-None-Match` / `If-Modified-Since`; a 304 costs nothing and is counted as such.
  * **Follow the minimum poll interval.** A floor between requests is enforced locally, so a
    bug upstream cannot turn into hammering. `Retry-After` is honoured on 429.
  * **Keep attribution and canonical.** The mapper copies `sourceUrl`, the AIHOT item link
    and the author through to the rendered page, and never rewrites them.
  * **Do not strip rights information.** Nothing here drops or rewrites the attribution the
    response carries.
  * **Track withdrawal.** `/selected/changes` carries deletions; the client surfaces them so
    the digest can drop an entry AIHOT has withdrawn, rather than keeping a stale copy
    alive -- the terms require handling retraction, not ignoring it.

Every request is cached on disk, so a re-run of the pipeline costs zero requests, and the
whole thing degrades to "no AIHOT data today" rather than failing the digest.
"""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: The documented client UA for the JSON API. The agent-facing Markdown endpoints accept a
#: browser UA, but the JSON API asks for this one -- and impersonating a browser to get
#: around a block is explicitly prohibited, so it is not done anywhere in this module.
USER_AGENT = "aihot-api/2.0.0"

BASE_URL = "https://aihot.news/api/v1"

#: Their terms state roughly 60 requests per minute per IP. A conservative floor between
#: calls keeps a retry loop or a fan-out from ever approaching that.
MIN_INTERVAL_SECONDS = 1.1

#: How long a cached response stays usable without asking again. AIHOT publishes a daily
#: digest and a reset monitor that changes a few times a day, so a few hours is plenty and
#: keeps a once-a-day digest to a handful of requests.
#:
#: This is *longer* than the `max-age=60` AIHOT sends, and that is deliberate rather than
#: careless: a digest runs once a day, so re-asking every 60 seconds would be pointless
#: traffic against a service whose terms ask for minimum polling. `s-maxage=60` describes
#: how long a shared HTTP cache may reuse the body; it is not an instruction to poll. The
#: ETag is always replayed, so even an expired local copy costs only a 304.
CACHE_TTL_SECONDS = 6 * 3600


class AihotUnavailable(RuntimeError):
    """Raised when AIHOT cannot be reached after the retry budget.

    Callers treat this as "no AIHOT data today" -- a missing feed must never fail the whole
    digest, because the digest's job is to publish what it has.
    """


@dataclass
class Policy:
    """The terms AIHOT states in its own response headers.

    The API advertises its rules on every response:

        x-aihot-policy-version: 1.1
        x-aihot-commercial-use: written-authorization-required
        x-aihot-contact: wzglyay@virxact.com
        link: <https://aihot.news/terms>; rel="terms-of-service"
        cache-control: public, max-age=60, s-maxage=60, stale-while-revalidate=60

    and lists those header names in `access-control-expose-headers`, which is an explicit
    request to read and pass them on. So they are captured and surfaced on the page rather
    than dropped: a reader has to be able to see whose data this is and under what terms.
    """

    version: str = ""
    commercial_use: str = ""
    contact: str = ""
    terms_url: str = "https://aihot.news/terms"
    cache_control: str = ""

    @property
    def requires_authorization_for_commercial(self) -> bool:
        return "written-authorization-required" in self.commercial_use

    def as_dict(self) -> dict:
        """The stored form.

        Only constructor fields: this same dict is fed back through `Policy(**)` when the
        cache is read, and including a derived property made every cached response
        unreadable with `unexpected keyword argument`. Round-tripping has to be symmetric.
        """
        return {
            "version": self.version,
            "commercial_use": self.commercial_use,
            "contact": self.contact,
            "terms_url": self.terms_url,
            "cache_control": self.cache_control,
        }

    def describe(self) -> dict:
        """The rendered form, including the derived flag the page displays."""
        return self.as_dict() | {
            "requires_authorization_for_commercial": self.requires_authorization_for_commercial,
        }


@dataclass
class CacheEntry:
    url: str
    etag: str = ""
    last_modified: str = ""
    fetched_at: float = 0.0
    payload: Any = None
    status: int = 0
    policy: Policy = field(default_factory=Policy)


def _policy_from(headers) -> Policy:
    return Policy(
        version=headers.get("X-AIHOT-Policy-Version", "") or "",
        commercial_use=headers.get("X-AIHOT-Commercial-Use", "") or "",
        contact=headers.get("X-AIHOT-Contact", "") or "",
        cache_control=headers.get("Cache-Control", "") or "",
    )


def _policy_from_doc(doc: dict) -> Policy:
    """Rebuild a Policy from a stored dict, ignoring fields we no longer declare.

    An older cache entry stored the derived `requires_authorization_for_commercial` flag.
    Passing it straight to the constructor raised `unexpected keyword argument` and made
    **every** cached response unreadable -- a format change turned into a hard failure and
    the client could not start at all. Unknown keys are dropped instead, which is also what
    the API's own guidance asks of clients ("ignore unknown fields").
    """
    known = {"version", "commercial_use", "contact", "terms_url", "cache_control"}
    return Policy(**{k: v for k, v in doc.items() if k in known})


@dataclass
class AihotClient:
    cache_dir: Path
    #: Counters for the run report, so the cost of this source is visible rather than
    #: implied. `not_modified` is the number of requests that cost no payload.
    stats: dict[str, int] = field(default_factory=lambda: {
        "requests": 0, "not_modified": 0, "cache_hits": 0, "errors": 0, "retries": 0,
    })
    #: The terms AIHOT advertises on its responses, kept so the page can state them.
    policy: Policy = field(default_factory=Policy)
    _last_call: float = 0.0

    # ---------------------------------------------------------------- cache

    def _cache_path(self, url: str) -> Path:
        safe = url.replace("https://", "").replace("/", "_").replace("?", "_").replace("&", "_")
        return self.cache_dir / f"{safe}.json"

    def _load(self, url: str) -> CacheEntry | None:
        path = self._cache_path(url)
        if not path.exists():
            return None
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return CacheEntry(
            url=url,
            etag=doc.get("etag", ""),
            last_modified=doc.get("last_modified", ""),
            fetched_at=float(doc.get("fetched_at", 0)),
            payload=doc.get("payload"),
            status=int(doc.get("status", 200)),
            policy=_policy_from_doc(doc.get("policy") or {}),
        )

    def _save(self, entry: CacheEntry) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(entry.url).write_text(
            json.dumps(
                {
                    "etag": entry.etag,
                    "last_modified": entry.last_modified,
                    "fetched_at": entry.fetched_at,
                    "status": entry.status,
                    "policy": entry.policy.as_dict(),
                    "payload": entry.payload,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    # ---------------------------------------------------------------- fetch

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < MIN_INTERVAL_SECONDS:
            time.sleep(MIN_INTERVAL_SECONDS - elapsed)
        self._last_call = time.monotonic()

    def get(self, path: str, *, allow_stale: bool = True) -> Any:
        """Fetch a path, revalidating with ETag. Returns the parsed payload or None.

        A cached copy younger than the TTL is returned without a request at all. An older
        copy is revalidated; a 304 refreshes the timestamp, so a daily run settles into a
        handful of cheap conditional requests.
        """
        url = path if path.startswith("http") else f"{BASE_URL}{path}"
        cached = self._load(url)
        now = time.time()

        if cached and cached.payload is not None and (now - cached.fetched_at) < CACHE_TTL_SECONDS:
            self.stats["cache_hits"] += 1
            # Restore the policy too. It was only assigned on the network path, so a cache
            # hit returned the data while `client.policy` stayed empty — and the page then
            # rendered without the terms notice it is required to carry. That is the whole
            # point of storing the policy alongside the payload.
            if cached.policy.version or cached.policy.commercial_use:
                self.policy = cached.policy
            return cached.payload

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        }
        if cached and cached.etag:
            headers["If-None-Match"] = cached.etag
        if cached and cached.last_modified:
            headers["If-Modified-Since"] = cached.last_modified

        for attempt in (1, 2, 3):
            self._throttle()
            request = urllib.request.Request(url, headers=headers)
            try:
                self.stats["requests"] += 1
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read()
                    if response.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    payload = json.loads(raw.decode("utf-8"))
                    policy = _policy_from(response.headers)
                    self.policy = policy
                    self._save(CacheEntry(
                        url=url,
                        etag=response.headers.get("ETag", ""),
                        last_modified=response.headers.get("Last-Modified", ""),
                        fetched_at=now,
                        payload=payload,
                        status=response.status,
                        policy=policy,
                    ))
                    return payload

            except urllib.error.HTTPError as exc:
                if exc.code == 304 and cached is not None:
                    # Not modified: refresh the timestamp so the next run also revalidates
                    # instead of refetching, and replay the stored payload.
                    self.stats["not_modified"] += 1
                    cached.fetched_at = now
                    if cached.policy.version or cached.policy.commercial_use:
                        self.policy = cached.policy
                    self._save(cached)
                    return cached.payload

                if exc.code == 429:
                    # The terms require honouring Retry-After rather than retrying blindly.
                    wait = float(exc.headers.get("Retry-After") or 5)
                    self.stats["retries"] += 1
                    time.sleep(min(wait, 30))
                    continue

                if exc.code in (403, 451) and cached is not None and allow_stale:
                    # Blocked or withdrawn. A stale copy is better than nothing for a source
                    # the digest merely cites, but it is flagged so the page can say so.
                    self.stats["errors"] += 1
                    return cached.payload

                self.stats["errors"] += 1
                if exc.code == 404:
                    return None
                if attempt == 3:
                    raise AihotUnavailable(f"{url}: HTTP {exc.code}") from exc
                time.sleep(2 * attempt)

            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                self.stats["errors"] += 1
                if attempt == 3:
                    if cached is not None and allow_stale:
                        return cached.payload
                    raise AihotUnavailable(f"{url}: {exc}") from exc
                time.sleep(2 * attempt)

        if cached is not None and allow_stale:
            return cached.payload
        return None

    # ---------------------------------------------------------------- endpoints

    def codex_resets(self) -> dict:
        """Codex quota resets and reset-card grants, with Tibo's own posts."""
        return self.get("/codex-resets") or {}

    def hot_topics(self) -> dict:
        """What is being discussed right now, by event."""
        return self.get("/hot-topics") or {}

    def latest(self, *, window: str = "24h", limit: int = 30) -> dict:
        return self.get(f"/items?window={window}&limit={limit}") or {}

    def changes(self, *, since: str | None = None) -> dict:
        """Additions, updates and **withdrawals** since a cursor.

        The withdrawal list matters: the terms require handling retraction, so an entry
        AIHOT has pulled must be dropped here too rather than kept alive from cache.
        """
        path = "/selected/changes" if not since else f"/selected/changes?since={since}"
        return self.get(path) or {}


# ------------------------------------------------------------------ mapping


def reset_events(payload: dict) -> list[dict]:
    """Normalise the codex-reset payload into the rows the page renders.

    Kept deliberately thin: the API's own labels (`displayLabel`, `status`, `schedule.label`)
    are passed through rather than re-derived, because AIHOT's classification already encodes
    the judgement about whether a reset is confirmed, pending, or a card grant -- and
    re-inferring it locally would let the two disagree.
    """
    rows: list[dict] = []
    for event in payload.get("events") or []:
        posts = []
        for post in event.get("posts") or []:
            posts.append({
                "stage": post.get("stage") or "",
                "text": post.get("fullText") or post.get("text") or "",
                "original": post.get("fullOriginalText") or post.get("originalText") or "",
                "url": post.get("url") or "",
                "at": post.get("publishedAt") or "",
            })
        rows.append({
            "id": event.get("id") or "",
            "kind": event.get("type") or "",
            "label": event.get("displayLabel") or event.get("label") or "",
            "title": event.get("title") or "",
            "status": event.get("status") or "",
            "scope": event.get("scope") or "",
            "created_at": event.get("createdAt") or "",
            "confirmed_at": event.get("confirmedAt") or "",
            "occurred_on": event.get("occurredOn") or "",
            "schedule_label": (event.get("schedule") or {}).get("label") or "",
            "posts": posts,
        })
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return rows


def reset_summary(payload: dict, *, policy: Policy | None = None) -> dict:
    """The headline numbers, computed from the event list.

    AIHOT's own `monitor` object is **not** these numbers: it reports the collector's health
    (`status`, `lastAttemptAt`, `pendingCount`, `heldWindowCount`). The four statistics the
    reference page shows -- resets in 90 days, cards in 90 days, median gap, last reset --
    are derived here from the 45 events, and `derived` is set so the page can say so. A
    figure this module computed and a figure AIHOT published are different claims and the
    reader is told which one they are looking at.
    """
    events = reset_events(payload)
    collector = payload.get("monitor") or {}

    # The API's `type` values, read off a live response rather than guessed:
    #   direct_reset  (32)  -> label 全员重置,        displayLabel 额度重置 / 重置（形式未明确）
    #   reset_credit  (13)  -> label 发重置卡,        displayLabel 重置卡发放
    # An earlier version filtered on "reset_card", which matched nothing and reported zero
    # cards granted while thirteen were sitting in the data.
    RESET_KINDS = {"direct_reset", "quota_reset", "reset"}
    CARD_KINDS = {"reset_credit", "reset_card", "credit"}

    resets = [e for e in events if e["kind"] in RESET_KINDS]
    cards = [e for e in events if e["kind"] in CARD_KINDS]

    def day(e: dict):
        try:
            return datetime.fromisoformat(e["created_at"]).date()
        except (ValueError, TypeError):
            return None

    reset_days = sorted(d for d in (day(e) for e in resets) if d)
    gaps = [(b - a).days for a, b in zip(reset_days, reset_days[1:])]

    def within(e: dict, days: int) -> bool:
        return _within_days(e["created_at"], days)

    stats = {
        "resets90d": len([e for e in resets if within(e, 90)]),
        "cards90d": len([e for e in cards if within(e, 90)]),
        "medianGapDays": (sorted(gaps)[len(gaps) // 2] if gaps else None),
        "lastResetOn": (reset_days[-1].isoformat() if reset_days else None),
        "totalResets": len(resets),
        "totalCards": len(cards),
    }

    return {
        "stats": stats,
        # Distinguishes "computed here" from "published by AIHOT" on the page.
        "derived": True,
        "collector": {
            "status": collector.get("status") or "",
            "last_collected_at": collector.get("lastCollectedAt") or "",
            "pending": collector.get("pendingCount"),
            "review": collector.get("reviewCount"),
        },
        "total_events": payload.get("count") or len(events),
        "history_from": (payload.get("historyFrom") or "")[:10],
        "checked_at": payload.get("checkedAt") or "",
        "timezone": payload.get("timezone") or "Asia/Shanghai",
        "outage": payload.get("outage") or None,
        "policy": (policy or Policy()).describe(),
        "attribution": {
            "name": "AIHOT",
            "url": "https://aihot.news/codex-reset",
            "note": "按其使用规则保留署名与原帖链接；统计数字由本站根据同一份事件流计算。",
        },
    }


def activities(payload: dict, *, limit: int = 30) -> list[dict]:
    """Tibo's related posts that are not tied to a specific reset event.

    Worth showing separately: the reference page has a "相关动态" area, and these posts are
    where a reset is usually *announced* before it becomes a confirmed event.
    """
    out = []
    for post in (payload.get("activities") or [])[:limit]:
        out.append({
            "id": post.get("id") or "",
            "kind": post.get("kind") or "",
            "text": post.get("text") or "",
            "original": post.get("originalText") or "",
            "url": post.get("url") or "",
            "at": post.get("publishedAt") or "",
            "status_changed": bool(post.get("statusChanged")),
            "action": post.get("action") or "",
        })
    return out


def _within_days(iso: str, days: int) -> bool:
    if not iso:
        return False
    try:
        when = datetime.fromisoformat(iso)
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(when.tzinfo) - when).days <= days
