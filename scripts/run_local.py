#!/usr/bin/env python3
"""Local runner: load model keys from a file into the environment, then run the pipeline.

Usage:
    python scripts/run_local.py <keys.json> run --from-items data/raw/items.jsonl

Keys are read from the file into environment variables **for this process only**. They
are never written to the repository and never printed, which is the same contract the
GitHub Actions workflow honours via Secrets.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

#: key-file platform/label substring -> (env var, default model)
KEY_MAP = {
    "groq": ("GROQ_API_KEY", "GROQ_MODEL", "openai/gpt-oss-20b"),
    # The `-latest` alias survives model retirement; a pinned id does not. Measured
    # 2026-10-14: `gemini-2.5-flash-lite` returns 404 "no longer available to new users".
    "generativelanguage": ("GEMINI_API_KEY", "GEMINI_MODEL", "gemini-flash-lite-latest"),
    "google": ("GEMINI_API_KEY", "GEMINI_MODEL", "gemini-flash-lite-latest"),
}


def load_keys(path: Path) -> dict[str, str]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for row in doc.get("keys") or []:
        blob = f"{row.get('platform','')} {row.get('label','')} {row.get('baseUrl','')}".lower()
        for needle, (key_env, model_env, model) in KEY_MAP.items():
            if needle in blob and key_env not in out:
                out[key_env] = str(row["key"])
                out.setdefault(model_env, model)
    return out


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    keys_path = Path(sys.argv[1])
    if not keys_path.exists():
        print(f"key file not found: {keys_path}")
        return 2

    found = load_keys(keys_path)
    for key, value in found.items():
        os.environ.setdefault(key, value)
    print(f"providers configured: {', '.join(k for k in found if k.endswith('_API_KEY')) or 'none'}")

    # Budget defaults for a local exploratory run: bounded, so a mistake cannot burn a
    # day's free quota.
    os.environ.setdefault("AIDAILY_LLM__MAX_CALLS_PER_RUN", "80")
    os.environ.setdefault("AIDAILY_LLM__MAX_TOKENS_PER_RUN", "400000")

    from aidaily.__main__ import main as cli_main

    return cli_main(sys.argv[2:])


if __name__ == "__main__":
    raise SystemExit(main())
