"""Information-source registry: load, validate, and guard against silent loss.

The registry is the single source of truth for what gets collected. Its most
important property is negative: **a source may never disappear without a trace.**
Every source carries `found_in` provenance back to the repository, file and config
key it was discovered in, and `assert_provenance_complete` fails loudly if any
audited record loses its home.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import yaml
from pydantic import ValidationError

from .models import SourceSpec

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "sources" / "registry.yaml"
DEFAULT_LEDGER = ROOT / "audit" / "sources_ledger.json"


class RegistryError(RuntimeError):
    pass


def load_registry(path: Path | str = DEFAULT_REGISTRY) -> list[SourceSpec]:
    p = Path(path)
    if not p.exists():
        raise RegistryError(f"registry not found: {p}")
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    raw = doc.get("sources")
    if not isinstance(raw, list) or not raw:
        raise RegistryError(f"registry has no sources: {p}")

    seen: set[str] = set()
    out: list[SourceSpec] = []
    for row in raw:
        try:
            spec = SourceSpec.model_validate(row)
        except ValidationError as exc:
            raise RegistryError(f"invalid source entry {row.get('source_id', row.get('url'))!r}: {exc}") from exc
        if spec.source_id in seen:
            raise RegistryError(f"duplicate source_id: {spec.source_id}")
        seen.add(spec.source_id)
        out.append(spec)
    return out


def registry_stats(sources: list[SourceSpec]) -> dict[str, int]:
    stats = {"total": len(sources), "enabled": 0, "needs_credential": 0, "disabled": 0}
    by_health: dict[str, int] = {}
    for s in sources:
        stats["enabled"] += int(s.enabled)
        if s.needs_credential:
            stats["needs_credential"] += 1
        if s.health_status == "disabled":
            stats["disabled"] += 1
        by_health[s.health_status] = by_health.get(s.health_status, 0) + 1
    stats.update({f"health_{k}": v for k, v in by_health.items()})
    return stats


def all_provenance(sources: list[SourceSpec]) -> Counter[str]:
    """Multiset of provenance entries across the registry.

    A Counter, not a set: `repo:file#key` is NOT unique -- 23 Horizon RSS feeds all
    live under `data/config.github.json#sources.rss[]`, and an array index would be
    fragile. Counting occurrences is what makes "no source was lost" checkable.
    """
    return Counter(entry for s in sources for entry in s.found_in)


def load_ledger(path: Path | str = DEFAULT_LEDGER) -> dict:
    p = Path(path)
    if not p.exists():
        raise RegistryError(f"ledger not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def ledger_provenance(ledger: dict) -> Counter[str]:
    """Occurrences of every `repo:file#key` triple the audit discovered."""
    return Counter(
        f"{r['repo']}:{r['file']}#{r['key']}" for r in ledger.get("raw_records", [])
    )


def assert_provenance_complete(sources: list[SourceSpec], ledger: dict) -> None:
    """Raise if any audited source location lost occurrences in the registry.

    This is the CI guard for the project's hardest promise: merging six repositories
    must not drop a source. Disabling a source is allowed (set `enabled: false` or add
    it to overrides); *deleting* it is not.
    """
    expected = ledger_provenance(ledger)
    actual = all_provenance(sources)
    missing = {k: v - actual.get(k, 0) for k, v in expected.items() if v > actual.get(k, 0)}
    if missing:
        detail = "\n  ".join(f"{k}  (audited {expected[k]}, registry has {actual.get(k, 0)})" for k in sorted(missing)[:20])
        raise RegistryError(
            f"{len(missing)} audited source location(s) lost entries in the registry "
            f"(sources must be disabled, never deleted):\n  {detail}"
        )


# --- overrides: the human correction layer ---------------------------------------
DEFAULT_OVERRIDES = ROOT / "sources" / "overrides.yaml"

# Fields a human may tune without touching the registry's provenance.
# `needs_credential` belongs here: whether a source now demands a token is an
# operational fact that changes over time (Reddit blocked anonymous access during this
# project), not part of the audit trail.
_OVERRIDABLE = {
    "enabled", "priority", "polling_interval", "category", "timeout_s",
    "notes", "fetch_method", "adapter", "dedup_group", "language", "needs_credential",
}
# Fields that are evidence, not knobs. Rewriting them would break the audit trail
# (`found_in`) or silently repoint a source at different content (`url`).
_IMMUTABLE = {"source_id", "url", "normalized_url", "found_in", "repositories",
              "provenance_count", "merged_parameter_rows", "params"}


def load_overrides(path: Path | str = DEFAULT_OVERRIDES) -> dict[str, dict]:
    p = Path(path)
    if not p.exists():
        return {}
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    rows = doc.get("overrides") or {}
    if not isinstance(rows, dict):
        raise RegistryError(f"overrides must be a mapping of source_id -> fields: {p}")
    for sid, fields in rows.items():
        if not isinstance(fields, dict):
            raise RegistryError(f"override for {sid!r} must be a mapping")
        bad = set(fields) & _IMMUTABLE
        if bad:
            raise RegistryError(
                f"override for {sid!r} tries to change immutable field(s) {sorted(bad)}; "
                "provenance and URL are evidence and cannot be edited"
            )
        unknown = set(fields) - _OVERRIDABLE - {"reason"}
        if unknown:
            raise RegistryError(f"override for {sid!r} has unknown field(s) {sorted(unknown)}")
    return rows


def apply_overrides(
    sources: list[SourceSpec], overrides: dict[str, dict] | None = None
) -> tuple[list[SourceSpec], list[str]]:
    """Apply the human correction layer. Never removes a source.

    Two guard rails, both deliberate:
      * an override that matches no source is an error, not a no-op -- a typo would
        otherwise mean "I disabled that noisy feed" silently did nothing;
      * disabling a source requires a written `reason`, so the next person can tell a
        considered decision from an accident.
    """
    overrides = overrides if overrides is not None else load_overrides()
    by_id = {s.source_id: s for s in sources}

    unknown_ids = sorted(set(overrides) - set(by_id))
    if unknown_ids:
        raise RegistryError(
            "override(s) reference unknown source_id: " + ", ".join(unknown_ids)
            + " -- fix the id or remove the override"
        )

    applied: list[str] = []
    out: list[SourceSpec] = []
    for spec in sources:
        fields = overrides.get(spec.source_id)
        if not fields:
            out.append(spec)
            continue

        if fields.get("enabled") is False and not (fields.get("reason") or "").strip():
            raise RegistryError(
                f"override for {spec.source_id!r} disables the source without a reason; "
                "a disabled source must say why so it can be reviewed later"
            )

        changed = {k: v for k, v in fields.items() if k not in ("reason",)}
        updated = spec.model_copy(
            update={
                **changed,
                "override_reason": fields.get("reason") or spec.override_reason,
                "overridden_fields": sorted(set(spec.overridden_fields) | set(changed)),
            }
        )
        out.append(updated)
        applied.append(
            f"{spec.source_id}: " + ", ".join(f"{k}={v!r}" for k, v in sorted(changed.items()))
            + (f"  ({fields['reason']})" if fields.get("reason") else "")
        )
    return out, applied
