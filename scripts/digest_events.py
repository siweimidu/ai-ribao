"""How many events does today's archived digest contain? 0 when there is none.

Used by the slot watchdog to decide whether a scheduled slot produced anything. The file can
exist from a run that wrote artefacts before the fact-check rejected them, so the event count is
what matters, not the file name.

Exit code is always 0: the caller reads the number, and a missing or broken file is simply 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if not argv:
        print(0)
        return 0
    path = Path(argv[0])
    if not path.exists():
        print(0)
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        print(len(payload["digest"]["top_events"]))
    except Exception:  # noqa: BLE001 - any unreadable archive counts as "no digest"
        print(0)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
