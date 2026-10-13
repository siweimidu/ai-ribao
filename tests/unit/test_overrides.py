"""The human correction layer must be safe to use and impossible to abuse.

These tests encode the three rules in sources/overrides.yaml: provenance is immutable,
a stale override is an error, and disabling a source requires a written reason.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from aidaily.registry import (
    RegistryError,
    all_provenance,
    apply_overrides,
    load_overrides,
    load_registry,
)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "sources" / "registry.yaml"
OVERRIDES = ROOT / "sources" / "overrides.yaml"


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "overrides.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_shipped_overrides_apply_cleanly() -> None:
    sources = load_registry(REGISTRY)
    overrides = load_overrides(OVERRIDES)
    updated, applied = apply_overrides(sources, overrides)

    assert len(updated) == len(sources), "overrides must never add or remove a source"
    assert applied, "the shipped overrides should have some effect"
    assert all(s.override_reason for s in updated if s.overridden_fields)


def test_disabled_source_stays_in_the_list() -> None:
    """Disabling is not deleting -- the record and its provenance must survive."""
    sources = load_registry(REGISTRY)
    updated, _ = apply_overrides(sources, load_overrides(OVERRIDES))

    ids_before = {s.source_id for s in sources}
    ids_after = {s.source_id for s in updated}
    assert ids_before == ids_after

    dead = next(s for s in updated if s.source_id == "api:git-trending-justlikemaki-vip-topone")
    assert dead.enabled is False
    assert dead.found_in, "a disabled source keeps its provenance"
    assert "TLS" in (dead.override_reason or "")


def test_provenance_is_untouched_by_overrides() -> None:
    """The audit trail is evidence: overrides must not be able to alter it."""
    sources = load_registry(REGISTRY)
    updated, _ = apply_overrides(sources, load_overrides(OVERRIDES))
    assert all_provenance(updated) == all_provenance(sources)


def test_reddit_requires_credentials_but_keeps_its_audited_url() -> None:
    """Reddit closed anonymous access, so the fix is credentials -- not a rewritten URL.

    Measured 2026-10-13: the JSON endpoints 403, and old.reddit.com answers 200 with a
    login page (302 -> /login/?reason=lor2). The source stays in the registry with its
    original URL; only `needs_credential` is set, so the collector skips it with a
    reason instead of reporting a silent zero.
    """
    sources = load_registry(REGISTRY)
    updated, _ = apply_overrides(sources, load_overrides(OVERRIDES))

    before = {s.source_id: s.url for s in sources if s.domain == "reddit.com"}
    after = {s.source_id: s.url for s in updated if s.domain == "reddit.com"}

    assert len(after) == 12
    assert after == before, "URL is evidence and must stay exactly as audited"

    for s in updated:
        if s.domain == "reddit.com":
            assert s.needs_credential == "REDDIT_CLIENT_ID"
            assert s.adapter == "RedditFetcher"

    old_reddit = [s for s in updated if s.domain == "old.reddit.com"]
    assert len(old_reddit) == 3
    assert all(s.needs_credential == "REDDIT_CLIENT_ID" for s in old_reddit)

    # And the collector agrees: they are skipped, with the credential named.
    from aidaily.collect import select_sources

    _, skipped = select_sources(updated)
    reddit_skips = [why for sid, why in skipped if "reddit" in sid]
    assert len(reddit_skips) == 15
    assert all("REDDIT_CLIENT_ID" in why for why in reddit_skips)


def test_priority_override_applies() -> None:
    sources = load_registry(REGISTRY)
    updated, _ = apply_overrides(sources, load_overrides(OVERRIDES))
    juya = next(s for s in updated if s.source_id == "rss:daily-juya-uk")
    assert juya.priority == 1


# --- guard rails ------------------------------------------------------------------
def test_disabling_without_a_reason_is_rejected(tmp_path: Path) -> None:
    """The next maintainer must be able to tell a decision from an accident."""
    sources = load_registry(REGISTRY)
    path = _write(tmp_path, 'overrides:\n  "rss:schneier-com":\n    enabled: false\n')
    with pytest.raises(RegistryError, match="without a reason"):
        apply_overrides(sources, load_overrides(path))


def test_disabling_with_a_reason_is_allowed(tmp_path: Path) -> None:
    sources = load_registry(REGISTRY)
    path = _write(
        tmp_path,
        'overrides:\n  "rss:schneier-com":\n    enabled: false\n    reason: "403 Forbidden"\n',
    )
    updated, applied = apply_overrides(sources, load_overrides(path))
    assert len(updated) == len(sources)
    assert any("schneier" in a for a in applied)


def test_unknown_source_id_is_rejected(tmp_path: Path) -> None:
    """A typo must not silently do nothing while the user believes it worked."""
    sources = load_registry(REGISTRY)
    path = _write(tmp_path, 'overrides:\n  "rss:does-not-exist":\n    priority: 1\n')
    with pytest.raises(RegistryError, match="unknown source_id"):
        apply_overrides(sources, load_overrides(path))


def test_immutable_fields_cannot_be_overridden(tmp_path: Path) -> None:
    """Repointing `url` would silently change what a source means."""
    for field, value in (
        ("url", "https://evil.example/feed.xml"),
        ("found_in", ["fake:file#key"]),
        ("source_id", "rss:renamed"),
    ):
        path = _write(tmp_path, f'overrides:\n  "rss:schneier-com":\n    {field}: {value!r}\n')
        with pytest.raises(RegistryError, match="immutable"):
            load_overrides(path)


def test_unknown_override_field_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, 'overrides:\n  "rss:schneier-com":\n    turbo_mode: true\n')
    with pytest.raises(RegistryError, match="unknown field"):
        load_overrides(path)


def test_missing_overrides_file_is_not_an_error() -> None:
    """A fresh clone must run without an overrides file."""
    assert load_overrides(Path("/nonexistent/overrides.yaml")) == {}


def test_overrides_file_is_valid_yaml_with_reasons() -> None:
    """Every entry in the shipped file documents itself."""
    doc = yaml.safe_load(OVERRIDES.read_text(encoding="utf-8"))
    rows = doc["overrides"]
    assert len(rows) >= 13
    for sid, fields in rows.items():
        assert "reason" in fields and fields["reason"].strip(), f"{sid} has no reason"
