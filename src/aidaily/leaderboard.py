"""Model leaderboard data, taken from artificialanalysis.ai.

## Where the numbers come from

The site is a Next.js app that streams its data as a series of
`self.__next_f.push([1, "..."]) ` chunks. The leaderboard page carries all 272 models in one
`initialModels` array inside that payload -- no pagination, no API key, one request.

Measured 2026-10-23: 1.9 MB of HTML, 657 KB of flight payload, 272 models parsed.

## Why the flight payload and not the rendered HTML

The page renders a table, but its rows are virtualised: the visible text carries only the first
screenful. The payload has every model with every benchmark, and it is the same data the page
itself uses -- parsing HTML would give a subset and break whenever the markup changes.

## What is kept

Enough to rank and to explain the rank: the intelligence index, the price per million tokens,
context window, size class, reasoning/open-weights flags, and the individual benchmarks that
make up the index. Fields the site leaves null stay null rather than becoming zero, so
"not measured" never reads as "scored 0".

## The row shape changed under us (2026-11-15)

Until 2026-11-14 a row carried `slug` at the top and each benchmark as a flat camelCase column
(`omniscienceAccuracy`, `tau2`, …). From 2026-11-15 the slug lives in `release.slug`, the
benchmarks live in a `scores` object keyed kebab-case (`omniscience-accuracy`, `tau2-bench`, …),
and `intelligenceIndexIsEstimated` is gone.

`_to_model` knew only the old shape, so every row lost its slug and was discarded: 287 rows in,
0 models out, `fetch_models` returned `[]`, and `load_models` fell back to the 2026-11-14
snapshot. The rendered page was byte-identical, so nothing was committed and the workflow stayed
green for a week while the published leaderboard did not move.

Both shapes are read now, and a payload whose rows no longer parse says so on stderr instead of
passing for "nothing to do".
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

LEADERBOARD_URL = "https://artificialanalysis.ai/leaderboards/models"
MODEL_URL = "https://artificialanalysis.ai/models/{slug}"

#: The site's audience clock. A fixed offset, not `zoneinfo`: Beijing has no DST, and
#: `scripts/missing_slots.py` already reasons about time this way.
_BEIJING = timezone(timedelta(hours=8))

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

#: One flight chunk. The payload is a concatenation of these.
_FLIGHT = re.compile(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)')


@dataclass
class Model:
    slug: str
    name: str
    creator: str
    intelligence: float | None = None
    estimated: bool = False
    price_input: float | None = None
    price_output: float | None = None
    context: int | None = None
    size_class: str | None = None
    reasoning: bool = False
    open_weights: bool = False
    deprecated: bool = False
    benchmarks: dict[str, float] = field(default_factory=dict)
    creator_color: str = ""
    #: The parenthetical from the source name, e.g. `Max, Default Fallback`. Shown beside
    #: the name in small type so the main column stays one line.
    variant: str = ""

    @property
    def href(self) -> str:
        return MODEL_URL.format(slug=self.slug)


def _flight_payload(url: str, *, timeout: float = 50.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "text/html"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", "replace")
    payload = "".join(_FLIGHT.findall(html))
    # The chunks are JS string literals: one unescape turns \" into " and \uXXXX into characters.
    try:
        return payload.encode().decode("unicode_escape")
    except Exception:
        return payload


def _array_after(text: str, marker: str) -> str | None:
    """The JSON array that follows `marker`, found by brace matching.

    A regex cannot do this: the array nests and contains brackets inside strings.
    """
    at = text.find(marker)
    if at < 0:
        return None
    start = text.find("[", at)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


#: Benchmarks worth carrying. The index is built from these, so they explain it.
#:
#: Keyed by the label the page shows; the value lists every source key that has carried it,
#: current shape first. Keeping both means the columns survive a reshape instead of emptying.
_BENCHMARKS = {
    "omniscience": ("omniscience-accuracy", "omniscienceAccuracy"),
    "terminalbench": ("terminalbench-hard", "terminalbenchHard"),
    "tau2": ("tau2-bench", "tau2"),
    "lcr": ("artificial-analysis-long-context-reasoning", "lcr"),
    "hle": ("humanitys-last-exam", "hle"),
    "gpqa": ("gpqa-diamond", "gpqa"),
    "ifbench": ("ifbench",),
    "scicode": ("scicode",),
    "mmmu": ("mmmu-pro", "mmmuPro"),
}


def _to_model(raw: dict) -> Model | None:
    # `release` is the 2026-11-15 home of the slug; older payloads carry it at the top level.
    release = raw.get("release") if isinstance(raw.get("release"), dict) else {}
    slug = str(raw.get("slug") or release.get("slug") or "").strip()
    name = str(raw.get("name") or raw.get("shortName") or release.get("name") or "").strip()
    if not slug or not name:
        return None

    # Same reshape: the benchmarks moved from flat columns into this object.
    scores = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}

    def number(key: str) -> float | None:
        value = raw.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        return None

    def benchmark(*keys: str) -> float | None:
        for key in keys:
            value = scores.get(key)
            if value is None:
                value = raw.get(key)
            # `bool` is an `int`; `True` must not read as a score of 1.
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        return None

    benchmarks: dict[str, float] = {}
    for label, keys in _BENCHMARKS.items():
        value = benchmark(*keys)
        if value is not None:
            benchmarks[label] = value

    # `Claude Opus 5.5 (Max, Default Fallback)` is 37 characters and wraps to three lines in a
    # table cell. The parenthetical names the reasoning-effort variant, which the 推理 badge
    # already signals; it moves to its own field so the name column stays one line.
    variant = ""
    if "(" in name and name.rstrip().endswith(")"):
        head, _, tail = name.rpartition("(")
        if head.strip():
            name = head.strip()
            variant = tail.rstrip(")").strip()

    return Model(
        slug=slug,
        name=name,
        variant=variant,
        creator=str(raw.get("modelCreatorName") or "").strip(),
        intelligence=number("intelligenceIndex"),
        estimated=bool(raw.get("intelligenceIndexIsEstimated")),
        price_input=number("price1mInputTokens"),
        price_output=number("price1mOutputTokens"),
        context=int(raw["contextWindowTokens"]) if isinstance(raw.get("contextWindowTokens"), (int, float)) else None,
        size_class=(str(raw["paramClass"]) if raw.get("paramClass") else None),
        reasoning=bool(raw.get("isReasoning")),
        open_weights=bool(raw.get("isOpenWeights")),
        deprecated=bool(raw.get("deprecated")),
        benchmarks=benchmarks,
        creator_color=str(raw.get("modelCreatorColor") or ""),
    )


def fetch_models(*, url: str = LEADERBOARD_URL, timeout: float = 50.0) -> list[Model]:
    """Every model on the leaderboard, ranked by intelligence index. Never raises.

    An empty list means the fetch failed or the payload's shape is no longer understood; the
    caller renders the page without a table rather than with a wrong one.

    Every path that yields no models says why on stderr. Returning `[]` in silence is what let
    this page sit unchanged for a week while the workflow stayed green: a reshape upstream looked
    exactly like "nothing to do".
    """
    try:
        payload = _flight_payload(url, timeout=timeout)
    except Exception as exc:
        print(f"leaderboard: 抓取失败：{exc!r}", file=sys.stderr)
        return []

    raw = _array_after(payload, '"initialModels":')
    if not raw:
        print(
            "leaderboard: payload 里没有 initialModels 数组，站点结构变了，解析器需要更新",
            file=sys.stderr,
        )
        return []
    try:
        rows = json.loads(raw)
    except ValueError as exc:
        print(f"leaderboard: initialModels 不是合法 JSON（{exc}），解析器需要更新", file=sys.stderr)
        return []

    models = [m for m in (_to_model(r) for r in rows if isinstance(r, dict)) if m]
    if rows and not models:
        print(
            f"leaderboard: {len(rows)} 行模型全部被丢弃，行结构变了（slug/name 或分数键位改了），"
            "解析器需要更新",
            file=sys.stderr,
        )
    models.sort(key=lambda m: (-(m.intelligence or -1e9), m.name.lower()))
    return models


def refresh_site_page(root: Path, *, max_age_hours: float = 6.0) -> tuple[bool, str]:
    """Rewrite `leaderboard.html` on its own, without building a digest.

    ## Why this exists

    The page used to be produced only inside `write_site`, which the `run` command calls only
    when the gate says the day still needs publishing. On a three-slot day that means the
    04:00 build writes the page and the 12:00 and 20:00 builds skip everything -- so the
    leaderboard showed data from before dawn while the rest of the site was current.

    This function is the escape hatch: it refreshes one page from the snapshot, touching
    nothing else, so a workflow can call it on runs that publish nothing.

    Returns `(changed, note)`. `changed` is False when the snapshot was already fresh enough,
    which keeps a no-op run from rewriting the file and dirtying the working tree.
    """
    from .site import SiteContext, render_leaderboard

    site = root / "data" / "digests" / "site"
    page = site / "leaderboard.html"
    if not site.exists():
        return False, f"{site} 不存在，无法刷新"

    snapshot = snapshot_path(root)
    age = snapshot_age_hours(root)
    models = load_models(root, max_age_hours=max_age_hours)
    if not models:
        return False, "取不到模型数据，页面保持原样" + (
            f"（快照已 {age:.0f} 小时）" if age is not None else "（没有可用快照）"
        )

    fetched_at = ""
    try:
        if snapshot.exists():
            fetched_at = _page_date(
                str(json.loads(snapshot.read_text(encoding="utf-8")).get("fetched_at") or "")
            )
    except Exception:
        pass

    # The rail needs a context; the archive is the only thing in it the page reads.
    ctx = SiteContext(archive=[], site_url="")
    html = render_leaderboard(ctx, models, fetched_at=fetched_at)

    if page.exists() and page.read_text(encoding="utf-8") == html:
        if age is not None and age > max_age_hours:
            return False, f"页面已是最新，但快照已 {age:.0f} 小时没更新，抓取没有成功"
        return False, "页面已是最新"
    page.write_text(html, encoding="utf-8")
    return True, f"已刷新 {page.name}（{len(models)} 个模型）"


def snapshot_path(root: Path) -> Path:
    return root / "data" / "state" / "leaderboard.json"


def _page_date(stamp: str) -> str:
    """The fetch stamp as the page shows it: a Beijing calendar date.

    The page says "抓取于 <date>" and the watchdog compares that string with Beijing time, so a
    UTC date reads as yesterday until 08:00 Beijing -- exactly the hours after the 04:00 build
    refreshed it. The page looked a day stale every morning while it was four hours old.
    """
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return stamp[:10]
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(_BEIJING).strftime("%Y-%m-%d")


def snapshot_age_hours(root: Path) -> float | None:
    """How old the saved snapshot is, or None when there is no readable snapshot.

    The page promises a fetch date, and a run that could not move it must be able to say how far
    behind it is: "unchanged" and "seven days stale" render identically otherwise.
    """
    path = snapshot_path(root)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        saved = datetime.fromisoformat(doc["fetched_at"])
    except Exception:
        return None
    if saved.tzinfo is None:
        saved = saved.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - saved).total_seconds() / 3600


def load_models(root: Path, *, max_age_hours: float = 6.0) -> list[Model]:
    """Models from the on-disk snapshot when it is fresh, else fetched and re-saved."""
    path = snapshot_path(root)
    now = datetime.now(timezone.utc)

    if path.exists():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            saved = datetime.fromisoformat(doc["fetched_at"])
            if saved.tzinfo is None:
                saved = saved.replace(tzinfo=timezone.utc)
            if (now - saved).total_seconds() < max_age_hours * 3600:
                return [Model(**row) for row in doc.get("models", [])]
        except Exception:
            pass

    models = fetch_models()
    if models:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "fetched_at": now.isoformat(),
                    "source": LEADERBOARD_URL,
                    "count": len(models),
                    "models": [m.__dict__ for m in models],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return models

    # Fetch failed: a stale snapshot beats an empty page.
    if path.exists():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            return [Model(**row) for row in doc.get("models", [])]
        except Exception:
            pass
    return []
