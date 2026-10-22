"""AIHOT's hot list, read as a ranking signal.

The rule: a hotter story, reported by more independent sources, should score higher. The hot
page publishes exactly that per event -- a heat score and the number of independent sources --
measured across 885 sources rather than the 138 this project collects itself.

Why scrape the rendered page: AIHOT is a React Router SSR app and publishes no public JSON
endpoint for the hot list. The data is embedded in the server-rendered payload, so the payload
is what we parse. The structure was read off the live page on 2026-10-22; the patterns are kept
loose about field order because that payload is minified.

Failure is not an error: a hot list we could not read contributes nothing, and ranking falls
back on the signals this project measures itself.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

#: Where the last successful read is kept. Heat moves on a 6-hour window, so an hourly read is
#: plenty and a failed fetch must not erase the previous one mid-run.
CACHE = Path("data") / "state" / "aihot_hot.json"

#: A key may be followed by `:` or `,` depending on the serializer. Both are accepted so a
#: payload that switches representation does not silently parse to nothing.
_SEP = r"[\s]*[:][\s]*"

_RANK = re.compile(r'"rank"' + _SEP + r'(\d+)')

_FIELD = {
    "heat": re.compile(r'"heat"' + _SEP + r'([0-9]+(?:\.[0-9]+)?)'),
    "trend": re.compile(r'"trend"' + _SEP + r'"([a-z]+)"'),
    "trend_pct": re.compile(r'"trendPct"' + _SEP + r'(-?[0-9]+(?:\.[0-9]+)?)'),
    "sources": re.compile(r'"sourceCount"' + _SEP + r'(\d+)'),
    "participants": re.compile(r'"participantCount"' + _SEP + r'(\d+)'),
}

_SUMMARY = re.compile(r'"summary"' + _SEP + r'"((?:[^"\\]|\\.){40,700})')


@dataclass(frozen=True)
class HotEntry:
    rank: int
    heat: float
    trend: str
    trend_pct: float
    sources: int
    participants: int
    summary: str


def parse_hot(payload: str) -> list[HotEntry]:
    """Read the hot entries out of a rendered `/hot` page.

    Each entry is cut at the next `"rank"` marker and read on its own: matching across the whole
    document would pair one rank with a heat value from three entries later.
    """
    text = payload or ""
    marks = [m.start() for m in _RANK.finditer(text)]
    entries: list[HotEntry] = []
    for index, start in enumerate(marks):
        end = marks[index + 1] if index + 1 < len(marks) else min(len(text), start + 4000)
        chunk = text[start:end]
        rank_m = _RANK.search(chunk)
        if not rank_m:
            continue
        values: dict[str, object] = {}
        for name, pattern in _FIELD.items():
            m = pattern.search(chunk)
            if not m:
                values = {}
                break
            raw = m.group(1)
            values[name] = raw if name == "trend" else float(raw)
        if not values:
            continue
        summary_m = _SUMMARY.search(chunk)
        summary = ""
        if summary_m:
            try:
                summary = json.loads('"' + summary_m.group(1) + '"')
            except Exception:
                summary = summary_m.group(1)
        entries.append(
            HotEntry(
                rank=int(rank_m.group(1)),
                heat=float(values["heat"]),
                trend=str(values["trend"]),
                trend_pct=float(values["trend_pct"]),
                sources=int(values["sources"]),
                participants=int(values["participants"]),
                summary=" ".join(summary.split())[:280],
            )
        )
    return entries


def save(entries: list[HotEntry], path: Path | None = None) -> None:
    target = path or CACHE
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "entries": [
            {
                "rank": e.rank,
                "heat": e.heat,
                "trend": e.trend,
                "trend_pct": e.trend_pct,
                "sources": e.sources,
                "participants": e.participants,
                "summary": e.summary,
            }
            for e in entries
        ],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def load(path: Path | None = None) -> list[HotEntry]:
    target = path or CACHE
    if not target.exists():
        return []
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: list[HotEntry] = []
    for row in payload.get("entries") or []:
        try:
            out.append(
                HotEntry(
                    rank=int(row["rank"]),
                    heat=float(row["heat"]),
                    trend=str(row.get("trend") or "flat"),
                    trend_pct=float(row.get("trend_pct") or 0),
                    sources=int(row.get("sources") or 0),
                    participants=int(row.get("participants") or 0),
                    summary=str(row.get("summary") or ""),
                )
            )
        except Exception:
            continue
    return out
