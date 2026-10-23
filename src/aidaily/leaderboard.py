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
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

LEADERBOARD_URL = "https://artificialanalysis.ai/leaderboards/models"
MODEL_URL = "https://artificialanalysis.ai/models/{slug}"

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
_BENCHMARKS = {
    "omniscienceAccuracy": "omniscience",
    "terminalbenchHard": "terminalbench",
    "tau2": "tau2",
    "lcr": "lcr",
    "hle": "hle",
    "gpqa": "gpqa",
    "ifbench": "ifbench",
    "scicode": "scicode",
    "mmmuPro": "mmmu",
}


def _to_model(raw: dict) -> Model | None:
    slug = str(raw.get("slug") or "").strip()
    name = str(raw.get("name") or raw.get("shortName") or "").strip()
    if not slug or not name:
        return None

    def number(key: str) -> float | None:
        value = raw.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        return None

    benchmarks: dict[str, float] = {}
    for key, label in _BENCHMARKS.items():
        value = number(key)
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

    An empty list means the fetch failed; the caller renders the page without a table rather
    than with a wrong one.
    """
    try:
        payload = _flight_payload(url, timeout=timeout)
    except Exception:
        return []

    raw = _array_after(payload, '"initialModels":')
    if not raw:
        return []
    try:
        rows = json.loads(raw)
    except ValueError:
        return []

    models = [m for m in (_to_model(r) for r in rows if isinstance(r, dict)) if m]
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
    models = load_models(root, max_age_hours=max_age_hours)
    if not models:
        return False, "取不到模型数据，页面保持原样"

    fetched_at = ""
    try:
        if snapshot.exists():
            fetched_at = str(json.loads(snapshot.read_text(encoding="utf-8")).get("fetched_at") or "")[:10]
    except Exception:
        pass

    # The rail needs a context; the archive is the only thing in it the page reads.
    ctx = SiteContext(archive=[], site_url="")
    html = render_leaderboard(ctx, models, fetched_at=fetched_at)

    if page.exists() and page.read_text(encoding="utf-8") == html:
        return False, "页面已是最新"
    page.write_text(html, encoding="utf-8")
    return True, f"已刷新 {page.name}（{len(models)} 个模型）"


def snapshot_path(root: Path) -> Path:
    return root / "data" / "state" / "leaderboard.json"


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
