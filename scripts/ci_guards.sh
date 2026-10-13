#!/usr/bin/env bash
# Local mirror of the CI guard steps.
#
# Exists because the guards are shell one-liners inside a workflow: the only way to know
# they pass is to run them, and finding out from a failed CI run on main costs a commit
# and a wait. Run this before pushing.
#
#     bash scripts/ci_guards.sh

set -uo pipefail

fail=0
note() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

note "1/4 no credential patterns"
# POSIX ERE only: `git grep -E` supports neither lookaround nor non-capturing groups, and
# both produce "Invalid preceding regular expression". The exit status is captured rather
# than branched on, because `if git grep ...; then` reads a syntax error (exit 2) as
# "no match" and reports the repository as clean.
SECRETS='(^|[^A-Za-z0-9])(sk-([A-Za-z0-9]{1,12}-){0,3}[A-Za-z0-9]{16,}|gsk_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{20,}|cfat_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|nvapi-[A-Za-z0-9_-]{20,})'
found=$(git grep -nIE "$SECRETS" -- . ':!*.lock')
status=$?
if [ "$status" -gt 1 ]; then
  echo "FAIL: git grep errored (exit $status) -- the guard checked nothing"
  fail=1
elif [ -n "$found" ]; then
  echo "$found"
  echo "FAIL: possible credential committed"
  fail=1
else
  echo "ok"
fi

note "2/4 no personal addresses"
PII='[A-Za-z0-9._%+-]+@(qq|gmail|163|outlook)\.com'
ALLOW='(xxx@|your_|your-|example@|noreply@|user@)'
pii_raw=$(git grep -nIE "$PII" -- . ':!*.lock' ':!audit/')
pii_status=$?
if [ "$pii_status" -gt 1 ]; then
  echo "FAIL: git grep errored (exit $pii_status) -- the guard checked nothing"
  fail=1
else
  pii_hits=$(printf '%s' "$pii_raw" | grep -vE "$ALLOW" || true)
  if [ -n "$pii_hits" ]; then
    echo "$pii_hits"
    echo "FAIL: personal email address in a tracked file"
    fail=1
  else
    echo "ok"
  fi
fi

note "3/4 config files carry no credentials"
if grep -nE '(api_key|apikey|token|password|cookie)[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9_-]{16,}' \
     sources/registry.yaml sources/overrides.yaml config/daily.yaml; then
  echo "FAIL: credential-looking value in a config file"
  fail=1
else
  echo "ok"
fi

note "4/4 registry is reproducible"
# `python` is not on PATH inside WSL on Windows; CI has `python`. Try both.
PY=$(command -v python || command -v python3)
if [ -z "$PY" ]; then
  echo "skip: no python on PATH"
else
  before=$(mktemp)
  cp sources/registry.yaml "$before"
  "$PY" scripts/build_registry.py >/dev/null
  if "$PY" - "$before" <<'PY'
import sys, yaml
before = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
after = yaml.safe_load(open("sources/registry.yaml", encoding="utf-8"))
a = [s["source_id"] for s in before["sources"]]
b = [s["source_id"] for s in after["sources"]]
if a != b:
    print("FAIL: source_id drift; overrides and critical_sources would break silently")
    for x, y in zip(a, b):
        if x != y:
            print(f"  {x} -> {y}")
    sys.exit(1)
print(f"ok ({len(a)} source ids stable)")
PY
  then :; else fail=1; fi
  cp "$before" sources/registry.yaml
  rm -f "$before"
fi

if [ "$fail" -ne 0 ]; then
  printf '\n\033[31mguards FAILED\033[0m\n'
  exit 1
fi
printf '\n\033[32mall guards passed\033[0m\n'
