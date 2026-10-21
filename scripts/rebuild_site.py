#!/usr/bin/env python3
"""Rebuild every published page from the archive, then refresh the index last.

## Why a separate script

`write_site` regenerates `index.html` on every call, and it builds the archive list from the
digest files present *at that moment*. Rendering issues one at a time therefore leaves the index
describing whatever the last call happened to see:

Measured on 2026-10-21 -- eight issues existed on disk, `load_archive` returned all eight, and the
served index linked only seven. 2026-10-21.html was reachable but unreachable from the home page,
because an earlier issue had been written after it. The page existed; the doorway did not.

This script renders every issue in **descending** date order and touches the newest one last, so
the final `write_site` call sees the complete archive and writes an index that lists everything.

Usage:
    python scripts/rebuild_site.py            # every archived issue
    python scripts/rebuild_site.py --dry      # report only
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIGESTS = ROOT / "data" / "digests"


def main() -> int:
    dry = "--dry" in sys.argv
    dates = sorted(
        (p.stem for p in DIGESTS.glob("????-??-??.json")),
        reverse=True,
    )
    if not dates:
        print("没有找到归档")
        return 1

    print(f"将重建 {len(dates)} 期：{dates[0]} … {dates[-1]}")
    if dry:
        return 0

    # Newest last. Every render rewrites index.html from the files on disk, so the last call
    # must happen when the archive is complete -- and it is complete as soon as nothing is
    # being written concurrently, which this ordering guarantees.
    for date in reversed(dates):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "rerender_site.py"), str(DIGESTS / f"{date}.json")],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        tail = (result.stdout or "").strip().splitlines()
        print(f"  {date}  {tail[-1] if tail else '(no output)'}")
        if result.returncode != 0:
            print((result.stderr or "")[:600])
            return result.returncode

    index = DIGESTS / "site" / "index.html"
    html = index.read_text(encoding="utf-8")
    missing = [d for d in dates if f'href="{d}.html"' not in html]
    if missing:
        print(f"::error::首页缺少这些日期的链接：{missing}")
        return 1
    print(f"首页已列出全部 {len(dates)} 期")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
