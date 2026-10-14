"""Contract guard: merging six repositories must never silently drop a source.

This is the machine-enforced form of the project's hardest promise. Disabling a
source is allowed; deleting it is not. If a future refactor, a "cleanup" or a
registry regeneration loses an audited source location, CI goes red here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aidaily.registry import (
    RegistryError,
    all_provenance,
    assert_provenance_complete,
    ledger_provenance,
    load_ledger,
    load_registry,
    registry_stats,
)

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "audit" / "sources_ledger.json"
REGISTRY = ROOT / "sources" / "registry.yaml"

pytestmark = pytest.mark.skipif(
    not (LEDGER.exists() and REGISTRY.exists()),
    reason="audit artifacts not present",
)


def test_every_audited_source_location_survives() -> None:
    """The core guard: no `repo:file#key` triple from the audit may go missing."""
    sources = load_registry(REGISTRY)
    ledger = load_ledger(LEDGER)
    assert_provenance_complete(sources, ledger)


def test_provenance_count_is_not_shrinking() -> None:
    """107 audited records were found across the six repositories.

    The count may only grow (new sources added). A drop means information was lost.
    Note `repo:file#key` is not unique -- 23 Horizon RSS feeds share one config key --
    so this compares occurrence counts, not distinct keys.
    """
    sources = load_registry(REGISTRY)
    ledger = load_ledger(LEDGER)
    expected = ledger_provenance(ledger)
    actual = all_provenance(sources)

    assert expected.total() == 107, "audit ledger changed; re-audit before adjusting"
    # The audited rows must all survive *and* every locally-added source must carry its own
    # provenance. 107 is the audited baseline; 109 is that plus the two `found_in` entries
    # on AIHOT's curated feed (`sources/local.yaml`). Asserting `== expected` alone would
    # fail on any local addition, and asserting a bare total would let an audited row be
    # swapped for a local one -- so the baseline is checked for containment and the total is
    # checked exactly.
    assert all(actual[k] >= v for k, v in expected.items()), "provenance rows were lost"
    local_rows = sum(v for k, v in actual.items() if k not in expected)
    assert local_rows == 2, f"unexpected local provenance rows: {local_rows}"
    assert actual.total() == expected.total() + 2


def test_registry_shape_is_stable() -> None:
    """81 endpoint-level sources: 80 audited + AIHOT's editorially curated feed.

    The audited 80 come from collapsing Google Trends' 20 keyword rows (counting them as
    separate sources would inflate completeness; dropping them would lose information, so
    they live in the parent source's `params`).

    The 81st is `rss:aihot-news-picks`, added through `sources/local.yaml`. It is a *local*
    addition rather than an audited one, so the number here changes only when a source is
    deliberately added -- which is exactly what this test is for.
    """
    sources = load_registry(REGISTRY)
    assert len(sources) == 81

    trend = [s for s in sources if s.domain == "trends.google.com"]
    assert len(trend) == 1, "the 20 trend keywords must be one source, not twenty"
    keywords = (trend[0].params or {}).get("keywords", [])
    assert len(keywords) == 20
    assert trend[0].merged_parameter_rows == 21  # 1 fetcher row + 20 keyword rows


def test_no_source_was_silently_enabled_or_deleted() -> None:
    """Disabled sources stay in the file with their reason, rather than vanishing.

    Counts are asserted exactly on purpose: a drop means a source was deleted (forbidden),
    and an unexplained rise means something was enabled without review.

    Current shape: 81 total = 54 collectable + 20 present-but-not-wired-up (Horizon
    presets/examples + Cloudflare's unregistered adapters) + 7 needing credentials.

    The 81st source is AIHOT's curated feed (see `sources/local.yaml`): the audited source
    `rss:aihot-news` points at `/feed/all.xml` (seven days of public activity) while the
    editorial picks live at `/feed.xml`. They share `dedup_group: aihot` via
    `sources/overrides.yaml`, so the pair cannot double-count as two independent sources.
    """
    sources = load_registry(REGISTRY)
    stats = registry_stats(sources)
    assert stats["total"] == 81
    assert stats["enabled"] == 54
    assert stats["disabled"] == 20, "Horizon presets/examples and unwired adapters are kept, not dropped"
    assert stats["needs_credential"] == 7


def test_every_source_carries_provenance() -> None:
    for spec in load_registry(REGISTRY):
        assert spec.found_in, f"{spec.source_id} has no provenance"
        assert spec.repositories, f"{spec.source_id} has no originating repository"
        for entry in spec.found_in:
            assert ":" in entry and "#" in entry, f"malformed provenance entry: {entry}"


def test_source_ids_are_unique() -> None:
    ids = [s.source_id for s in load_registry(REGISTRY)]
    assert len(ids) == len(set(ids))


def test_guard_actually_fails_when_a_source_is_removed() -> None:
    """A guard that cannot fail is not a guard -- prove it detects loss."""
    sources = load_registry(REGISTRY)
    ledger = load_ledger(LEDGER)

    # Every source gone: the guard must notice.
    with pytest.raises(RegistryError, match="lost entries in the registry"):
        assert_provenance_complete([], ledger)

    # One unique provenance entry removed: still noticed. daily-briefing contributes
    # exactly one source, so dropping it must trip the guard.
    trimmed = [s for s in sources if "daily-briefing:agent.py#search_news()" not in s.found_in]
    assert len(trimmed) == len(sources) - 1
    with pytest.raises(RegistryError, match="daily-briefing"):
        assert_provenance_complete(trimmed, ledger)

    # And the intact registry passes.
    assert_provenance_complete(sources, ledger)


def test_registry_rejects_duplicate_ids(tmp_path: Path) -> None:
    bad = tmp_path / "registry.yaml"
    bad.write_text(
        "sources:\n"
        + "".join(
            "  - source_id: rss:dup\n    name: dup\n    url: https://example.com/a\n"
            "    normalized_url: https://example.com/a\n    domain: example.com\n"
            "    category: media\n    source_type: rss\n    found_in: [x:y#z]\n    repositories: [x]\n"
            for _ in range(2)
        ),
        encoding="utf-8",
    )
    with pytest.raises(RegistryError, match="duplicate source_id"):
        load_registry(bad)
