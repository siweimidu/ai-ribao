"""The two paper sources, and the generic JSON mapping they rely on.

HF Daily Papers returns a top-level list whose records look like
`{paper: {id}, publishedAt, title, summary}`. The generic extractor handled a list, but the
paper id lives one level down, so every item mapped to no URL and the source reported 0 items
while the endpoint was healthy. arXiv's /list/cs.AI/recent RSS is RDF, which feedparser reads
as zero entries -- the feed looked empty and was not.

These tests pin the parts that made those two fail, without touching the network.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from aidaily.fetchers.jsonapi import _DATE_KEYS, _dig, _map_record, _records
from aidaily.models import SourceSpec

ROOT = Path(__file__).resolve().parents[2]

HF_RECORD = {
    "paper": {"id": "2611.03806"},
    "publishedAt": "2026-11-02T00:00:00.000Z",
    "title": "BEND 2.0: Benchmarking the Capabilities Needed to Detect AI Text",
    "summary": "A benchmark.",
}

HF_PARAMS = {
    "title_key": "title",
    "summary_key": "summary",
    "id_key": "paper.id",
    "url_template": "https://huggingface.co/papers/{id}",
}


def _spec(params: dict, domain: str = "huggingface.co") -> SourceSpec:
    return SourceSpec(
        source_id="api:hf-daily-papers",
        name="HF",
        url="https://huggingface.co/api/daily_papers",
        normalized_url="https://huggingface.co/api/daily_papers",
        domain=domain,
        category="research",
        language="en",
        source_type="api",
        adapter="JsonApiFetcher",
        params=params,
    )


def test_a_top_level_list_is_records() -> None:
    assert _records([HF_RECORD]) == [HF_RECORD]


def test_a_dotted_field_path_reaches_the_paper_id() -> None:
    assert _dig(HF_RECORD, "paper.id") == "2611.03806"


def test_the_paper_url_is_built_from_the_nested_id() -> None:
    item = _map_record(_spec(HF_PARAMS), HF_RECORD)
    assert item is not None
    assert str(item.url) == "https://huggingface.co/papers/2611.03806"
    assert item.title.startswith("BEND 2.0")


def test_hugging_face_date_field_is_known() -> None:
    assert "publishedAt" in _DATE_KEYS


def test_both_paper_sources_are_registered_and_enabled() -> None:
    doc = yaml.safe_load((ROOT / "sources" / "local.yaml").read_text(encoding="utf-8"))
    by_id = {s["source_id"]: s for s in doc["sources"] if isinstance(s, dict)}
    for sid in ("api:hf-daily-papers", "rss:arxiv-cs-ai"):
        assert sid in by_id, sid
        assert by_id[sid]["enabled"] is True, sid
        assert by_id[sid].get("normalized_url"), sid


def test_arxiv_uses_the_atom_api_not_the_rdf_listing() -> None:
    doc = yaml.safe_load((ROOT / "sources" / "local.yaml").read_text(encoding="utf-8"))
    entry = {s["source_id"]: s for s in doc["sources"] if isinstance(s, dict)}["rss:arxiv-cs-ai"]
    assert "api/query" in entry["url"]
    assert "list/cs.AI" not in entry["url"]