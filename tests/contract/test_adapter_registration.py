"""Every registered adapter name must resolve to a class.

Measured 2026-10-24: `BilibiliHotFetcher` was written, tested in isolation, and registered in
`sources/local.yaml` -- but never added to the `ADAPTERS` dict. The collector skipped the source
silently: no error, no log line, just zero items. The digest had no Bilibili entries and nothing
said why.

A source whose adapter does not resolve is worse than a broken one: a broken one reports a
failure, this one reports nothing.
"""

from __future__ import annotations

from pathlib import Path

from aidaily.fetchers import ADAPTERS, resolve_adapter
from aidaily.registry import load_registry

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "sources" / "registry.yaml"


def test_every_source_adapter_resolves_to_a_known_class() -> None:
    """A typo or a missing registration would drop the source without a word."""
    unresolved = []
    for spec in load_registry(REGISTRY):
        if not spec.enabled:
            continue
        name = resolve_adapter(spec)
        if name is None or name not in ADAPTERS:
            unresolved.append((spec.source_id, name))
    assert not unresolved, f"adapters that do not resolve: {unresolved}"


def test_the_bilibili_adapter_is_registered() -> None:
    """The specific miss that motivated this file."""
    assert "BilibiliHotFetcher" in ADAPTERS


def test_every_adapter_class_exposes_a_name() -> None:
    """`BaseFetcher.name` is what the collect report prints; a missing one hides failures."""
    for key, cls in ADAPTERS.items():
        assert getattr(cls, "name", ""), f"{key} has no name attribute"