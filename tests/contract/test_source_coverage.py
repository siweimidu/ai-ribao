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
    # provenance. 107 is the audited baseline; the local rows are on top of it. The baseline
    # is checked for containment so a local row cannot be swapped in for an audited one, and
    # the local count is checked exactly so an addition has to be deliberate.
    assert all(actual[k] >= v for k, v in expected.items()), "provenance rows were lost"

    # 2 from AIHOT's curated feed; 36 from the user-supplied list of 2026-10-15;
    # 12 from AIHOT's demo sources of 2026-10-19
    # (`user-list:2026-10-15#用户提供的信息源清单`). Bumping this number is the point at which
    # 9 more on 2026-10-20 for cross-source corroboration (`user-list:2026-10-20#cross-source-coverage`).
    # a human confirms a new source was added on purpose.
    local_rows = sum(v for k, v in actual.items() if k not in expected)
    assert local_rows == 72, f"unexpected local provenance rows: {local_rows}"
    assert actual.total() == expected.total() + 72


def test_registry_shape_is_stable() -> None:
    """151 endpoint-level sources: 80 audited + 71 local additions.

    The audited 80 come from collapsing Google Trends' 20 keyword rows (counting them as
    separate sources would inflate completeness; dropping them would lose information, so
    they live in the parent source's `params`).

    The 49 local ones are AIHOT's curated feed, the 36 sources the user supplied on 2026-10-15,
    and the 12 taken from AIHOT's demo list on 2026-10-19 (`industry/sources.json`), each verified
    for reachability before being added. The number here changes only when a source is
    deliberately added -- which is exactly what this test is for.
    """
    sources = load_registry(REGISTRY)
    assert len(sources) == 151

    trend = [s for s in sources if s.domain == "trends.google.com"]
    assert len(trend) == 1, "the 20 trend keywords must be one source, not twenty"
    keywords = (trend[0].params or {}).get("keywords", [])
    assert len(keywords) == 20
    assert trend[0].merged_parameter_rows == 21  # 1 fetcher row + 20 keyword rows


def test_no_source_was_silently_enabled_or_deleted() -> None:
    """Disabled sources stay in the file with their reason, rather than vanishing.

    Counts are asserted exactly on purpose: a drop means a source was deleted (forbidden),
    and an unexplained rise means something was enabled without review.

    Current shape: 151 total = 124 collectable + 27 present-but-not-wired-up (Horizon
    presets/examples + Cloudflare's unregistered adapters) + 7 needing credentials.

    AIHOT's curated feed and the 36 user-supplied sources are local additions; see
    `sources/local.yaml`. The AIHOT pair shares `dedup_group: aihot`, and the user-supplied
    feeds are grouped per publisher, so neither can double-count as independent sources.
    """
    sources = load_registry(REGISTRY)
    stats = registry_stats(sources)
    assert stats["total"] == 151
    assert stats["enabled"] == 124
    assert stats["disabled"] == 20, "Horizon presets/examples and unwired adapters are kept, not dropped"
    assert stats["needs_credential"] == 7


def test_every_source_carries_provenance() -> None:
    """Every source is traceable, in one of two forms.

    An **audited** source traces to the repository it was found in (`repo:file#key`) and
    names that repository in `repositories`.

    A **locally-added** source traces to the list it came from
    (`user-list:2026-10-15#...`) and has no originating repository -- because it has none.
    Requiring a `repositories` entry here would mean inventing one, and a fabricated
    provenance is worse than an absent field: it would defeat the purpose of the check while
    appearing to satisfy it.
    """
    for spec in load_registry(REGISTRY):
        assert spec.found_in, f"{spec.source_id} has no provenance"
        for entry in spec.found_in:
            assert ":" in entry and "#" in entry, f"malformed provenance entry: {entry}"

        audited = any(not e.startswith("user-list:") for e in spec.found_in)
        if audited:
            assert spec.repositories, f"{spec.source_id} has no originating repository"
        else:
            # Locally added: the reason it was included stands in for the audit trail.
            assert spec.why, f"{spec.source_id} is local and states no reason for inclusion"


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
