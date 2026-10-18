"""The audit that runs in CI, tested against archives it is given.

`dedup_audit` exists because every deduplication regression of one week was found by the
reader, not the pipeline. These tests pin what it must catch, and -- just as important -- what
it must not flag, since a noisy audit gets ignored.
"""

from __future__ import annotations

import json

from aidaily.dedup_audit import audit


def write_issue(root, date: str, titles: list[str]) -> None:
    events = [
        {
            "event_id": "%s-%d" % (date, i),
            "primary_item_id": "i%d" % i,
            "title": title,
            "member_item_ids": ["i%d" % i],
            "source_ids": ["rss:a"],
            "all_urls": ["https://example.com/%s/%d" % (date, i)],
            "first_seen_at": date + "T00:00:00+00:00",
            "last_updated_at": date + "T00:00:00+00:00",
            "rank_score": 50.0,
        }
        for i, title in enumerate(titles)
    ]
    payload = {
        "digest": {"date": date, "top_events": events, "counts": {"events": len(events)},
                   "generated_at": date + "T00:00:00+00:00"},
        "sections": {},
        "insights": {},
    }
    (root / (date + ".json")).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_a_clean_archive_passes(tmp_path) -> None:
    write_issue(tmp_path, "2026-10-14", ["OpenAI 发布 GPT-6 Astra Pro", "阿里 Qwen 开源新基准"])
    write_issue(tmp_path, "2026-10-15", ["DeepSeek 发布 V4.1-Flash", "微软完成 MAI-Base-2 预训练"])
    report = audit(tmp_path, window_days=7)
    assert report.ok, report.render()


def test_a_model_spanning_several_days_is_flagged(tmp_path) -> None:
    """The Gemini 4 case: three distinct events, three days, reads as one story told thrice."""
    write_issue(tmp_path, "2026-10-14", ["Gemini 4 Argon 机器人模型发布"])
    write_issue(tmp_path, "2026-10-15", ["Gemini 4 Argon 开放研究者申请"])
    write_issue(tmp_path, "2026-10-16", ["Gemini 4 Argon 向 Pro 用户开放"])
    report = audit(tmp_path, window_days=7)
    rules = [f.rule for f in report.findings]
    assert "spans-days" in rules, report.render()


def test_two_entries_about_one_model_in_one_issue_are_flagged(tmp_path) -> None:
    write_issue(tmp_path, "2026-10-14", [
        "Gemini 4 Argon 机器人模型发布",
        "Gemini 4 Argon 全面开放，实测难撼 Claude Opus 5.5",
    ])
    report = audit(tmp_path, window_days=7)
    rules = [f.rule for f in report.findings]
    assert "same-issue" in rules, report.render()


def test_another_outlets_digest_is_flagged(tmp_path) -> None:
    write_issue(tmp_path, "2026-10-14", ["AI 早报：Gemini 4 Argon 全球开放，多家厂商发布新模型"])
    report = audit(tmp_path, window_days=7)
    assert any(f.rule == "roundup" for f in report.findings), report.render()


def test_an_exact_headline_twice_is_flagged(tmp_path) -> None:
    write_issue(tmp_path, "2026-10-14", ["OpenAI 发布 GPT-6 Astra Pro"])
    write_issue(tmp_path, "2026-10-16", ["OpenAI 发布 GPT-6 Astra Pro"])
    report = audit(tmp_path, window_days=7)
    assert any(f.rule == "exact-repeat" for f in report.findings), report.render()


def test_an_empty_archive_is_reported_not_silently_ok(tmp_path) -> None:
    """A missing archive must fail loudly: an audit that passes on no data is worse than none."""
    report = audit(tmp_path, window_days=7)
    assert not report.ok
    assert report.findings[0].rule == "archive"
