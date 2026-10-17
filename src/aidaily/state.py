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

#: Default collection hours (Beijing) when a caller does not pass `slot_hours`.
DEFAULT_SLOT_HOURS: tuple[int, ...] = (4, 12, 20)


def _slot_index(hour: int, slot_hours: tuple[int, ...] | list[int] | None) -> int | None:
    """Which scheduled slot a Beijing `hour` belongs to.

    A slot runs from its scheduled hour until the next slot's hour, so 04:00-11:59 is slot 0,
    12:00-19:59 is slot 1, and 20:00-03:59 is slot 2. Returning the index lets the gate compare
    "which collection published last" with "which collection is running now" instead of guessing
    a fixed split point, which is how the 12:00 and 20:00 runs came to be treated as one.
    """
    hours = tuple(sorted(slot_hours or DEFAULT_SLOT_HOURS))
    if not hours:
        return None
    index = len(hours) - 1          # before the first slot belongs to the last (yesterday's tail)
    for i, start in enumerate(hours):
        if hour >= start:
            index = i
    return index


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
    slot: int | None = None,
    slot_hours: tuple[int, ...] | list[int] | None = None,
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

    # Several collections a day are several publications of the same date. Keyed on the date
    # alone, the gate made every later run a permanent no-op -- the first run published, and
    # everything after it was told "already published" even though that slot's news had not been
    # collected. A slot is the scheduled collection a run belongs to; the gate skips only a
    # repeat *of the same slot*, which is what it exists for.
    #
    # The boundary is **derived from `slot_hours`**, not hard-coded. The previous version split
    # the day at 13:00 with `0 if hour < 13 else 1`, which silently merged slots 2 and 3 into
    # one once the schedule grew to three: the 12:00 run published, and the 20:00 run was told it
    # was a repeat of the same slot and skipped -- the evening's news never arrived. Measured on
    # 2026-10-17: the issue's window closed at 14:38 Beijing, so the whole afternoon was missing.
    if slot is not None and records[-1].status == "published":
        last_at = str(records[-1].at or "")
        try:
            last_hour = (int(last_at[11:13]) + 8) % 24  # ledger stores UTC; Beijing = UTC+8
            last_slot = _slot_index(last_hour, slot_hours)
        except ValueError:
            last_slot = slot
        if last_slot is not None and last_slot != slot:
            return True, f"{date} 已在上一个时段发布，本时段照常重建（含新增信息，去重合并）", {}

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
