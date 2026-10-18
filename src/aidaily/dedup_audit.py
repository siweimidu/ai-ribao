"""Audit the archive for repetition. Exits non-zero when a rule is broken.

## Why a separate command

Deduplication ran for months and was wrong three times in a row without anyone noticing:

* Gemini 4 appeared nine times across four issues (2026-10-14..17);
* the DeepSeek V4.1 launch was deleted as a "repeat" of an unrelated Meta story, because every
  WeChat URL collapsed to one fingerprint;
* another outlet's digest was republished inside our own.

Every one of those was found by the reader, not by the pipeline. The rules existed; nothing
checked that they were working. This command is that check, and `daily.yml` runs it after
publishing so a regression turns the workflow red on the day it happens.

It reads only the archived digests, so it can be run against any window at any time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date as Date
from pathlib import Path

from .designation import designation, is_roundup

#: A model may legitimately appear on several days while its story develops, but not more than
#: this inside one window without being reported. Measured: the Gemini 4 story ran on four
#: consecutive days before the cross-day rules caught it.
MAX_DAYS_PER_MODEL = 2


@dataclass
class Finding:
    rule: str
    detail: str


@dataclass
class AuditReport:
    dates: list[str] = field(default_factory=list)
    events: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings

    def render(self) -> str:
        lines = [
            "去重审计：%d 期 / %d 条事件" % (len(self.dates), self.events),
            "  期次：" + " ".join(self.dates),
        ]
        if self.ok:
            lines.append("  全部规则通过")
        else:
            lines.append("  %d 项违规：" % len(self.findings))
            for f in self.findings:
                lines.append("    [%s] %s" % (f.rule, f.detail))
        return "\n".join(lines)


def _load(path: Path) -> tuple[str, list[dict], dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    events = payload["digest"]["top_events"]
    insights = payload.get("insights") or {}
    return path.stem, events, insights


def _shown(event: dict, insights: dict) -> str:
    return (insights.get(event.get("event_id")) or {}).get("title") or event.get("title") or ""


def audit(digest_dir: Path, *, window_days: int = 7) -> AuditReport:
    """Check the archived issues for the repetition rules the pipeline promises to enforce."""
    report = AuditReport()
    paths = sorted(p for p in digest_dir.glob("????-??-??.json"))[-window_days:]
    if not paths:
        report.findings.append(Finding("archive", "没有找到任何归档，无法审计"))
        return report

    #: model designation -> dates it appeared on
    days_of: dict[str, set[str]] = {}
    #: model designation -> dates within one issue
    seen_titles: dict[str, str] = {}

    for path in paths:
        date, events, insights = _load(path)
        report.dates.append(date)
        report.events += len(events)

        per_issue: dict[str, list[str]] = {}
        for event in events:
            title = _shown(event, insights)

            # Rule 1: another outlet's digest must never be republished as a story.
            if is_roundup(title):
                report.findings.append(Finding("roundup", "%s 收录了别家日报：%s" % (date, title[:48])))

            model = designation(title)
            if model:
                days_of.setdefault(model, set()).add(date)
                per_issue.setdefault(model, []).append(title)

            # Rule 2: an exact headline may not appear twice inside the window.
            if title in seen_titles:
                report.findings.append(Finding(
                    "exact-repeat",
                    "%s 与 %s 标题相同：%s" % (date, seen_titles[title], title[:44]),
                ))
            else:
                seen_titles[title] = date

        # Rule 3: one model, one issue -- more than one entry means clustering failed.
        for model, titles in per_issue.items():
            if len(titles) > 1:
                report.findings.append(Finding(
                    "same-issue",
                    "%s 的 %s 有 %d 条：%s" % (date, model, len(titles), " / ".join(t[:26] for t in titles)),
                ))

    # Rule 4: a model may not dominate the window day after day.
    for model, days in sorted(days_of.items()):
        if len(days) > MAX_DAYS_PER_MODEL:
            report.findings.append(Finding(
                "spans-days",
                "%s 在 %d 期出现：%s" % (model, len(days), " ".join(sorted(days))),
            ))

    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="dedup-audit", description=__doc__.splitlines()[0])
    parser.add_argument("--digests", default="data/digests", help="归档目录")
    parser.add_argument("--window", type=int, default=7, help="检查最近多少期")
    args = parser.parse_args(argv)

    report = audit(Path(args.digests), window_days=args.window)
    print(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
