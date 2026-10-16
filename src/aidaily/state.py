"""Run ledger and idempotency gate.

GitHub Actions fires the schedule several times per morning and may drop or delay any of
them, so every trigger has to answer one question cheaply: *has today already been
published?* That answer lives here, in a small append-only ledger, rather than in the
workflow's own logic -- which means the gate can run as the very first step and skip the
entire expensive job when there is nothing to do.

The rule the gate enforces:

* the first trigger that gets all the way to "published" wins;
* every later trigger becomes a no-op;
* a **partial** publication (some delivery channel failed) is recorded as partial, so the
  next trigger resumes only the missing channel instead of re-sending everything.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER = ROOT / "data" / "state" / "runs.jsonl"

#: Overridable so a test or a dry run never touches the real publication ledger.
LEDGER_ENV = "AIDAILY_RUN_LEDGER"


def ledger_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    import os

    if env_path := os.environ.get(LEDGER_ENV):
        return Path(env_path)
    return DEFAULT_LEDGER

#: Exit codes the workflow branches on. Distinct from 1 so that "already done" is never
#: confused with "something broke".
EXIT_ALREADY_PUBLISHED = 10


@dataclass
class RunRecord:
    date: str
    status: str                    # published | partial | failed
    at: str
    digest_id: str = ""
    channels: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    llm: dict[str, object] = field(default_factory=dict)


def read_ledger(path: Path | str | None = None) -> list[RunRecord]:
    p = ledger_path(path)
    if not p.exists():
        return []
    out: list[RunRecord] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            # A corrupt line must not make the day unrecoverable: skip it and move on.
            continue
        try:
            out.append(RunRecord(**{k: doc[k] for k in ("date", "status", "at")}
                                 | {k: v for k, v in doc.items() if k not in ("date", "status", "at")}))
        except TypeError:
            continue
    return out


def append_record(record: RunRecord, path: Path | str | None = None) -> Path:
    p = ledger_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record.__dict__, ensure_ascii=False) + "\n")
    return p


def gate(
    date: str,
    path: Path | str | None = None,
    *,
    digest_id: str | None = None,
    artifact_dir: Path | str | None = None,
) -> tuple[bool, str, dict[str, str]]:
    """Decide whether this trigger should publish.

    Returns (should_publish, reason, channels_already_done). A previous *partial* run
    returns True with the already-succeeded channels listed, so the caller can resume.

    `digest_id` guards a real inconsistency that shipped. The ledger records "published"
    per *date*, but a later trigger on the same day builds a **different** digest -- new
    items arrived and 219 events became 223. Skipping every channel then left the published
    page describing 219 events while its own archived JSON said 223: the site contradicted
    its own data, and nothing in the pipeline noticed.

    So a differing `digest_id` re-publishes. This is not "ignore the gate": a repeat of the
    *same* content is still a no-op, which is what the gate exists for.
    """
    records = [r for r in read_ledger(path) if r.date == date]
    if not records:
        return True, f"{date} 尚未发布", {}

    # **The ledger records intent; the artifact is the thing itself.**
    #
    # A scheduled run reported "already published" for a date whose digest had been deleted:
    # three ledger rows said published while data/digests/2026-10-16.json did not exist.
    # The gate would have skipped that date forever -- there is no digest, and no future
    # trigger would ever build one. When the archive is missing, the honest answer is that the
    # date is *not* published, whatever the ledger says.
    if artifact_dir is not None and records[-1].status == "published":
        archive = Path(artifact_dir) / f"{date}.json"
        if not archive.exists():
            return True, (
                f"{date} 账本记为已发布，但归档 {archive.name} 不存在 —— "
                f"按未发布处理并重建"
            ), {}

    latest = records[-1]
    if latest.status == "published":
        if digest_id and latest.digest_id and latest.digest_id != digest_id:
            return True, (
                f"{date} 已发布，但本次内容不同"
                f"（{latest.digest_id} → {digest_id}），重新分发"
            ), {}
        return False, f"{date} 已发布（{latest.at}）", dict(latest.channels)
    if latest.status == "partial":
        done = {k: v for k, v in latest.channels.items() if v == "ok"}
        return True, f"{date} 上次为部分发布，补发未成功的通道", done
    return True, f"{date} 上次状态 {latest.status}，重试", {}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
