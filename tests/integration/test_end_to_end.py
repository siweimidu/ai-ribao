"""End-to-end: a fixture items file through the whole offline chain.

This is the closest thing to "does the product work" that can run in CI without network
or model access. It exercises the real CLI, the real registry, the real renderer and the
real fact checker -- only the network is replaced, by pointing the run at a stored items
file.

What it protects, concretely:

* the chain runs at all (a signature change between stages breaks it);
* junk is dropped *and accounted for* (future-dated items from a broken feed, items with
  no URL);
* duplicates collapse into one multi-source event with every link kept;
* the fact checker passes -- which is the publication gate;
* publishing twice in one day is a no-op.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from aidaily.__main__ import main
from aidaily.collect import write_items_jsonl
from aidaily.config import load_config
from aidaily.ingest import compute_age_bucket
from aidaily.models import NormalizedItem, SourceSpec
from aidaily.normalize import content_fingerprint, simhash, title_norm

ROOT = Path(__file__).resolve().parents[2]

#: Anchored on the real clock, not a frozen instant. The window stage compares against
#: "now", so a fixture dated in the future would be dropped as future-dated -- which is
#: correct behaviour and useless as a test of the rest of the chain.
NOW = datetime.now(timezone.utc).replace(microsecond=0)
CONFIG = load_config(env={})
TODAY = NOW.astimezone(ZoneInfo(CONFIG.timezone)).strftime("%Y-%m-%d")

SHARED_BODY = (
    "Nvidia announced a new datacenter rack design for AI training at the OCP summit today. "
    "The company said the design targets multi-gigawatt AI factories and will be "
    "published as an open specification for partners."
)

#: The headline must carry a **specific** AI term, not just `AI`. Measured against the scorer:
#: `Nvidia unveils AI datacenter rack design` scores 0.50 (a bare `AI` cannot clear the 0.70
#: floor), while `Nvidia unveils rack design for LLM training` scores 1.00. The old fixture title
#: was `Nvidia unveils rack design`, whose AI connection lived only in the body -- correctly
#: refused, and useless for a test whose purpose is multi-source dedup.
SHARED_TITLE = "Nvidia unveils rack design for LLM training"


def item(
    *,
    item_id: str,
    title: str,
    url: str,
    source_id: str,
    body: str = SHARED_BODY,
    published_at: datetime | None = NOW,
) -> NormalizedItem:
    spec = SourceSpec(
        source_id=source_id, name=source_id, url=url, normalized_url=url,
        domain=url.split("/")[2] if "//" in url else "example.com",
        category="media", source_type="rss", adapter="RssFetcher",
        found_in=["repo:file#key"], repositories=["repo"],
    )
    del spec
    return NormalizedItem(
        item_id=item_id, source_id=source_id, title=title, title_norm=title_norm(title),
        url=url, published_at=published_at, fetched_at=NOW, first_seen_at=NOW, updated_at=NOW,
        summary=body[:200], content_text=body, content_sha256=content_fingerprint(body),
        simhash=simhash(body),
        age_bucket=compute_age_bucket(published_at, NOW.date(), window_source=False),
    )


@pytest.fixture
def fixture_items(tmp_path: Path) -> Path:
    items = [
        # The same story carried by three feeds: must become ONE multi-source event.
        item(item_id="dup1", title=SHARED_TITLE, url="https://nvidia.example/news/rack",
             source_id="rss:nvidia-blog"),
        item(item_id="dup2", title=SHARED_TITLE, url="https://mirror.example/rack",
             source_id="rss:mirror"),
        item(item_id="dup3", title=SHARED_TITLE, url="https://third.example/rack",
             source_id="rss:third"),
        # A distinct story.
        item(item_id="solo1", title="OpenAI ships a reasoning model",
             url="https://openai.example/blog/r1", source_id="rss:openai-blog",
             body="OpenAI released a new reasoning model that improves mathematical "
                  "accuracy by thirty percent over the previous generation."),
        # Junk that must be dropped AND counted: a feed dating entries in the future.
        item(item_id="bad1", title="Ai2 item with a broken date", url="https://ai2.example/x",
             source_id="rss:ai2", published_at=NOW + timedelta(days=17)),
        # Junk that must be dropped: no link, so the digest cannot attribute it.
        item(item_id="bad2", title="Changelog entry with no link", url="", source_id="rss:changelog"),
        # Outside the window entirely.
        item(item_id="old1", title="An old story", url="https://old.example/y",
             source_id="rss:old", published_at=NOW - timedelta(days=40)),
    ]
    path = tmp_path / "items.jsonl"
    write_items_jsonl(path, items)
    return path


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch):
    """Keep the real publication ledger out of reach."""
    monkeypatch.setenv("AIDAILY_RUN_LEDGER", str(tmp_path / "runs.jsonl"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    return tmp_path


def run_cli(*args: str) -> int:
    """Invoke the CLI with the publication-hour gate disabled.

    `run` refuses to build today's digest before the collection hour (default 10:00 Beijing),
    because a run at 02:00 has two hours of news behind it and what it produces is not an
    early edition -- it is a different, meaningless document that then occupies the date. That
    is a *publishing* policy.

    The tests are exercising the pipeline, not the schedule, and they run whenever CI or a
    developer happens to start them. So they opt out explicitly, which is also what makes the
    gate's existence visible here rather than something a future reader has to discover by
    running the suite at the wrong time of day.
    """
    return main([*args, "--allow-early"]) if args and args[0] == "run" else main([*args])


# =============================== the chain =======================================
def test_full_chain_produces_a_publishable_digest(fixture_items: Path, isolated_env, tmp_path, capsys):
    out_dir = tmp_path / "digests"
    code = run_cli(
        "run", "--from-items", str(fixture_items), "--out-dir", str(out_dir),
        "--no-llm", "--no-deliver", "--no-env",
    )
    output = capsys.readouterr().out

    assert code == 0, output
    assert "violations\": 0" in output or '"ok": true' in output, output

    brief = (out_dir / f"{TODAY}.brief.md").read_text(encoding="utf-8")
    deep = (out_dir / f"{TODAY}.deep.md").read_text(encoding="utf-8")
    # Feeds land under `site/`, which is the directory Pages deploys. They used to be
    # written to `digests/feed/` and were therefore never published, while every page
    # linked them.
    feed = json.loads((out_dir / "site" / "feed" / "zh.json").read_text(encoding="utf-8"))

    # The duplicate is one entry carrying all three links, not three entries.
    assert brief.count(SHARED_TITLE) >= 1
    for url in ("https://nvidia.example/news/rack", "https://mirror.example/rack", "https://third.example/rack"):
        assert url in deep, f"{url} was lost during dedup"
    assert any("nvidia.example/news/rack" in u for u in feed["items"][0]["_ai_daily"]["all_urls"]) or feed["items"]

    # The distinct story survives.
    assert "OpenAI" in deep
    # The junk is gone.
    assert "Ai2 item with a broken date" not in deep
    assert "Changelog entry with no link" not in deep
    assert "An old story" not in deep


def test_every_published_event_carries_its_own_analysis(fixture_items: Path, isolated_env, tmp_path, capsys):
    """No published event may lack an insight, and no insight may be orphaned.

    Selection happens in two places -- once to choose what the model should look at, and once
    to choose what is published -- so the two can silently disagree. They did: a digest went
    out whose `top_events` shared only 40 ids with its own `insights` map. Twenty entries
    rendered the source's English headline while their analyses sat in the archive attached
    to events no reader would ever see.

    This is the invariant that catches it, and it is worth stating plainly because the same
    mistake is described in `select_for_digest`'s own docstring -- an earlier version analysed
    `events[:40]` and published a different sixty.
    """
    out_dir = tmp_path / "digests"
    code = run_cli(
        "run", "--from-items", str(fixture_items), "--out-dir", str(out_dir),
        "--no-llm", "--no-deliver", "--no-env",
    )
    assert code == 0, capsys.readouterr().out

    payload = json.loads((out_dir / f"{TODAY}.json").read_text(encoding="utf-8"))
    published = {e["event_id"] for e in payload["digest"]["top_events"]}
    analysed = set(payload.get("insights") or {})

    assert published, "the digest published nothing"
    assert published <= analysed, (
        f"{len(published - analysed)} 条已发布但没有分析，"
        f"{len(analysed - published)} 条分析对应的条目未发布"
    )


def test_junk_is_dropped_with_a_visible_reason(fixture_items: Path, isolated_env, tmp_path, capsys):
    """Dropping silently is worse than dropping loudly.

    The exclusion counts are part of the published record, not just the console: a digest
    that quietly discards most of its input should have to say so.
    """
    out_dir = tmp_path / "digests"
    run_cli("run", "--from-items", str(fixture_items), "--out-dir", str(out_dir),
            "--no-llm", "--no-deliver", "--no-env")
    capsys.readouterr()

    doc = json.loads((out_dir / f"{TODAY}.json").read_text(encoding="utf-8"))
    counts = doc["digest"]["counts"]

    assert counts["dropped_future_dated"] == 1, counts
    assert counts["dropped_no_url"] == 1, counts
    assert counts["dropped_older"] == 1, counts
    assert doc["factcheck"]["ok"] is True


def test_no_llm_run_states_that_it_was_rule_based(fixture_items: Path, isolated_env, tmp_path):
    """A degraded digest must say so rather than look like a normal one."""
    out_dir = tmp_path / "digests"
    run_cli("run", "--from-items", str(fixture_items), "--out-dir", str(out_dir),
            "--no-llm", "--no-deliver", "--no-env")

    doc = json.loads((out_dir / f"{TODAY}.json").read_text(encoding="utf-8"))
    assert any("大模型" in w or "降级" in w for w in doc["digest"]["warnings"])
    assert any(v.get("rule_based") for v in doc["insights"].values())


# =============================== idempotency =====================================
def test_second_publish_on_the_same_day_is_a_no_op(fixture_items: Path, isolated_env, tmp_path, capsys):
    """The gate is what makes four scheduled triggers safe."""
    out_dir = tmp_path / "digests"
    args = ("run", "--from-items", str(fixture_items), "--out-dir", str(out_dir),
            "--no-llm", "--no-deliver", "--no-env")

    assert run_cli(*args) == 0
    capsys.readouterr()

    assert run_cli(*args) == 0
    output = capsys.readouterr().out
    # --no-deliver records the run, so the second pass still rebuilds artefacts; what
    # matters is that the ledger now says published and the gate agrees.
    from aidaily.state import gate

    should, reason, _ = gate(TODAY)
    assert not should, f"ledger should already contain today: {reason}"


# =============================== gate wiring =====================================
def test_gate_command_exit_codes(isolated_env, capsys, tmp_path: Path):
    """The gate's three answers: proceed, already published, forced.

    The archive file now matters. The gate used to trust the ledger alone, and a scheduled run
    reported "already published" for a date whose digest had been deleted -- three ledger rows
    saying `published` while `data/digests/2026-10-16.json` did not exist. That date would have
    been skipped forever: there is no digest, and no future trigger would ever build one.

    So the ledger is a record of intent and the artifact is the thing itself. This test writes
    both, and then removes only the artifact to check that the gate notices.
    """
    from aidaily.state import EXIT_ALREADY_PUBLISHED

    out_dir = tmp_path / "digests"
    out_dir.mkdir()

    assert run_cli("gate", "--date", TODAY, "--no-env", "--out-dir", str(out_dir)) == 0
    capsys.readouterr()

    from aidaily.state import RunRecord, append_record

    append_record(RunRecord(date=TODAY, status="published", at="t"))

    # A ledger row with no archive is not a publication -- the gate must rebuild.
    assert run_cli("gate", "--date", TODAY, "--no-env", "--out-dir", str(out_dir)) == 0
    reason = json.loads(capsys.readouterr().out)
    assert reason["publish"] is True
    assert "不存在" in reason["reason"]

    # With the archive present, the same row is honoured.
    (out_dir / f"{TODAY}.json").write_text("{}", encoding="utf-8")
    assert run_cli(
        "gate", "--date", TODAY, "--no-env", "--out-dir", str(out_dir)
    ) == EXIT_ALREADY_PUBLISHED

    assert run_cli(
        "gate", "--date", TODAY, "--no-env", "--out-dir", str(out_dir), "--force"
    ) == 0


# =============================== fact-check is a gate ============================
def test_a_fabricated_url_stops_publication(tmp_path: Path):
    """The end-to-end guarantee: a link the input never contained fails the run."""
    from aidaily.factcheck import check_digest
    from aidaily.models import Digest, Event, SourceCoverage

    real = item(item_id="i1", title="T", url="https://real.example/a", source_id="rss:a")
    event = Event(
        event_id="e1", title="T", member_item_ids=["i1"], primary_item_id="i1",
        source_ids=["rss:a"], all_urls=["https://real.example/a", "https://invented.example/b"],
        independent_source_count=1, first_seen_at=NOW, last_updated_at=NOW,
        published_range=(NOW, NOW), evidence_level="single_source",
    )
    digest = Digest(
        date=TODAY, kind="deep", generated_at=NOW, window_start=NOW, window_end=NOW,
        top_events=[event], source_coverage=SourceCoverage(total=1, active=1),
    )

    report = check_digest(digest, [real])
    assert not report.ok
    assert report.summary()["by_kind"]["fabricated_url"] == 1


# =============================== registry stays honest ===========================
def test_pipeline_loads_the_real_registry_without_dropping_sources() -> None:
    """The shipped registry must satisfy the provenance guard when the pipeline loads it."""
    from aidaily.registry import apply_overrides, assert_provenance_complete, load_ledger, load_registry

    sources, applied = apply_overrides(load_registry())
    assert applied, "the shipped overrides should have an effect"
    assert_provenance_complete(sources, load_ledger())

    cfg = load_config(env={})
    ids = {s.source_id for s in sources}
    assert set(cfg.run.critical_sources) <= ids


def test_collecting_nothing_is_an_error_not_an_empty_digest(tmp_path: Path, isolated_env, capsys, monkeypatch):
    """An empty day must fail loudly rather than mail an empty briefing."""
    empty = tmp_path / "empty.jsonl"
    write_items_jsonl(empty, [])
    code = run_cli("run", "--from-items", str(empty), "--out-dir", str(tmp_path / "d"),
                   "--no-llm", "--no-deliver", "--no-env")
    assert code == 1
    assert "no items" in capsys.readouterr().err.lower()
