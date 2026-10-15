"""Profiles: the four-file unit that decides scope, score, and output shape.

## What this replaces, and why it matters

There was one file, `config/profile.md`, holding a single scoring rubric. Horizon splits the
job into four, and reading theirs showed why the split is not decoration:

| file | answers |
|---|---|
| `match.md` | does this belong to the section at all? |
| `analysis.md` | how important is it? |
| `enrichment.md` | how is it written, and when should a block be left empty? |
| `profile.json` | which prompts, which blocks, what is primary, which tools each block may use |

Conflating the first two is the specific mistake: a model asked "rate this 0-10 and decide if
it belongs" answers both with one number, and uses *not important* to reject *not in scope*.
Those need opposite handling -- out of scope means exclude, unimportant means rank lower.

## Beyond Horizon

Three additions, each from a measured failure in this project:

* **A relevance gate is part of the profile.** Horizon's profiles are per-topic and route
  between each other; this one has to first answer "is this AI at all", because a digest that
  accepts anything mentioning AI published an Apple smart speaker, Xbox game ports and VXNA
  chatter about mortgage debt in its top twenty.
* **`match.md` carries the real false positives.** The measured items are written into the
  prompt, so the judgement is anchored to examples rather than to an adjective.
* **Blocks are the four epistemic buckets.** `facts` / `inferences` / `opinions` /
  `uncertainties` already exist in this pipeline; the profile declares their required-ness and
  tells the model when a block should be left empty, which is the part Horizon states plainly
  ("Omit the block if it only predicts a broad industry trend") and the part this project was
  missing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

PROFILES_DIR = Path(__file__).resolve().parents[2] / "config" / "profiles"
DEFAULT_PROFILE_ID = "ai-daily"


@dataclass
class Block:
    id: str
    label: str = ""
    description: str = ""
    primary: bool = False
    required: bool = False
    tools: list[str] = field(default_factory=list)


@dataclass
class Profile:
    id: str
    name: str
    match: str
    analysis: str
    enrichment: str
    blocks: list[Block] = field(default_factory=list)
    scoring: dict = field(default_factory=dict)
    relevance_gate: dict = field(default_factory=dict)
    citations: dict = field(default_factory=dict)
    language: str = "zh"
    source: Path | None = None

    @property
    def primary_block(self) -> Block | None:
        for b in self.blocks:
            if b.primary:
                return b
        return self.blocks[0] if self.blocks else None

    @property
    def required_blocks(self) -> list[Block]:
        return [b for b in self.blocks if b.required]

    def summary(self) -> str:
        return (
            f"{self.id}（{self.name}）"
            f" · {len(self.blocks)} 个块"
            f"（必填 {len(self.required_blocks)}）"
            f" · 档位 {len(self.scoring.get('bands') or {})}"
        )


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def load_profile(profile_id: str = DEFAULT_PROFILE_ID, *, root: Path | None = None) -> Profile | None:
    """Load one profile directory, or None when it is not there.

    Returning None rather than raising: the pipeline must keep working on a checkout where
    `config/profiles/` was never created, and the callers fall back to their built-in prompts.
    A missing profile degrades the wording of the digest, not its existence.
    """
    directory = (root or PROFILES_DIR) / profile_id
    manifest = directory / "profile.json"
    if not manifest.exists():
        return None
    try:
        doc = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    enrichment = doc.get("enrichment") or {}
    blocks = [
        Block(
            id=str(b.get("id") or ""),
            label=str(b.get("label") or ""),
            description=str(b.get("description") or ""),
            primary=bool(b.get("primary")),
            required=bool(b.get("required")),
            tools=[str(t) for t in (b.get("tools") or [])],
        )
        for b in (enrichment.get("blocks") or [])
        if isinstance(b, dict) and b.get("id")
    ]

    return Profile(
        id=str(doc.get("id") or profile_id),
        name=str(doc.get("name") or profile_id),
        match=_read(directory / str(doc.get("match") or "match.md")),
        analysis=_read(directory / str(doc.get("analysis") or "analysis.md")),
        enrichment=_read(directory / str(enrichment.get("prompt") or "enrichment.md")),
        blocks=blocks,
        scoring=doc.get("scoring") or {},
        relevance_gate=doc.get("relevance_gate") or {},
        citations=doc.get("citations") or {},
        language=str(doc.get("language") or "zh"),
        source=directory,
    )


def available_profiles(*, root: Path | None = None) -> list[str]:
    base = root or PROFILES_DIR
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if (p / "profile.json").exists())
