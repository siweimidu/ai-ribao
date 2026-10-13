"""Contract guard for the CI guards themselves.

The secret-scanning step is a shell one-liner inside a workflow, which makes it easy to
get subtly wrong and impossible to notice when it is wrong:

* too loose, and it fails the build on ordinary text, so someone disables it;
* too strict, and a real key sails through.

Both directions have already happened here: the first version matched
`ri[sk-for-teens]-after-parental-alerts` inside an English digest body, and the version
before that silently exempted the whole `tests/` directory.

These tests read the actual patterns out of the workflow file, so the guard under test is
the guard that runs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"


def ci_text() -> str:
    return CI.read_text(encoding="utf-8")


def extract_patterns(step_marker: str) -> list[str]:
    """Pull `PATTERNS='...'` out of the named step."""
    text = ci_text()
    start = text.find(step_marker)
    assert start != -1, f"step not found in ci.yml: {step_marker}"
    block = text[start:start + 4000]
    return re.findall(r"PATTERNS='([^']+)'", block)


@pytest.fixture(scope="module")
def secret_re() -> re.Pattern[str]:
    patterns = extract_patterns("No secrets in the repository")
    assert patterns, "secret pattern not found in ci.yml"
    pattern = patterns[0]
    # The guard runs in three regex engines: `git grep -E` (POSIX ERE) in CI, GNU grep in
    # scripts/ci_guards.sh, and Python here. POSIX ERE supports neither lookaround nor
    # non-capturing groups, and either one makes `git grep` exit 2 with "Invalid preceding
    # regular expression" -- which inside `if cmd` reads as "no match", so the guard
    # printed "clean" while checking nothing at all. Both were tried for real.
    assert "(?<" not in pattern, (
        "lookaround is not POSIX ERE; `git grep -E` cannot parse it and would silently "
        "match nothing. Write the boundary as (^|[^A-Za-z0-9])."
    )
    assert "(?:" not in pattern, (
        "non-capturing groups are not POSIX ERE either; use a plain (...)."
    )
    return re.compile(pattern)


@pytest.fixture(scope="module")
def pii_re() -> re.Pattern[str]:
    patterns = extract_patterns("No PII in tracked files")
    assert patterns, "PII pattern not found in ci.yml"
    return re.compile(patterns[0])


# =============================== secrets =========================================
@pytest.mark.parametrize(
    "text",
    [
        # Real-world digest prose that the first version of the guard flagged.
        "sk-for-teens-after-parental-alerts-failed",
        "risk-and-cautious-investor-sentiment",
        "risk-over-100000-users-of-popular-car-tinkering",
        "task-expands-north-american-e-commerce-delivery",
        "risk-has-lost-his-lawsuit-against-sam-altman",
        # Ordinary words that merely contain "sk".
        "desk-organisation-and-multi-robot-collaboration",
        "brisk-wanted-an-openai-for-profit",
        # A sentence legitimately beginning with "sk-" plus hyphenated words. A lookbehind
        # cannot help here; only the "trailing opaque blob" requirement can.
        "sk-for-teens-after-parental-alerts",
        "sk-ills-and-hyphenated-prose-are-not-credentials",
    ],
)
def test_guard_does_not_fire_on_ordinary_english(secret_re, text: str) -> None:
    """A guard that cries wolf on normal content gets turned off, which is worse than none."""
    assert not secret_re.search(text), f"false positive on legitimate text: {text!r}"


#: Key-shaped strings the guard must catch, assembled at runtime.
#:
#: None of these may appear literally in this file. The guard scans the whole tree, so a
#: literal fixture is indistinguishable from a real leak -- it flagged `AKIA`+`IOSFODNN7
#: EXAMPLE` (AWS's own published example) the first time the guard actually ran. Building
#: the strings here keeps the fixture expressive and the repository genuinely clean.
def _key(*parts: str) -> str:
    return "".join(parts)


SECRET_SHAPED_STRINGS = [
    _key("sk-proj-", "A" * 40),
    _key("sk-", "x9" * 20),
    _key("gsk_", "a" * 40),
    _key("ghp_", "A" * 36),
    _key("github_pat_", "A" * 30),
    _key("cfat_", "A" * 30),
    _key("AKIA", "IOSFODNN7EXAMPLE"),
    _key("nvapi-", "A" * 30),
    _key("key = sk-", "z8" * 20),
    _key("token:gsk_", "Z" * 32),
]


@pytest.mark.parametrize("text", SECRET_SHAPED_STRINGS)
def test_guard_still_fires_on_real_looking_keys(secret_re, text: str) -> None:
    assert secret_re.search(text), f"real-looking credential not detected: {text!r}"


def test_guard_covers_the_credential_shapes_this_project_uses() -> None:
    """The project uses Google, Groq, GitHub and Cloudflare credentials; all must be covered."""
    pattern = ci_text()
    for family in ("sk-", "gsk_", "ghp_", "github_pat_", "cfat_", "AKIA", "nvapi-"):
        assert family in pattern, f"{family} is not covered by the secret guard"


def test_guard_is_not_scoped_away_from_whole_directories() -> None:
    """An earlier version excluded `tests/` entirely, which is where a fixture key would
    most plausibly be pasted by accident."""
    text = ci_text()
    start = text.find("No secrets in the repository")
    # Wide enough to include the `git grep` line itself, which sits after a long comment.
    block = text[start:start + 2500]
    assert ":!tests/*" not in block
    assert ":!*.lock" in block, "lockfiles must stay excluded; they contain hashes, not keys"


def test_guard_cannot_pass_by_accident() -> None:
    """The failure mode that actually happened: a grep syntax error reads as "no match".

    `if git grep ...; then fail; fi` treats *any* non-zero exit -- including a regex
    syntax error, exit 2 -- as "nothing found". The guard must capture the exit status
    and the output separately, so an error and a clean result cannot be confused.
    """
    text = ci_text()
    start = text.find("No secrets in the repository")
    block = text[start:start + 3000]
    assert "found=$(git grep" in block, "guard must capture git grep's output"
    assert "status=$?" in block, "guard must capture git grep's exit status"
    assert '"$status" -gt 1' in block, "exit 2 means the pattern itself was invalid"
    assert 'if [ -n "$found" ]' in block


# =============================== PII =============================================
#: Addresses the PII guard must catch. Built by concatenation so that no literal address
#: exists in this file -- otherwise the guard flags its own test fixture, which is exactly
#: what happened on the first CI run (and the address it flagged was a real person's).
LOOKALIKE_ADDRESSES = [
    "real.person" + "@gmail.com",
    "1234567890" + "@qq.com",
    "someone" + "@163.com",
    "x" + "@outlook.com",
]


@pytest.mark.parametrize("text", LOOKALIKE_ADDRESSES)
def test_pii_guard_fires_on_personal_addresses(pii_re, text: str) -> None:
    assert pii_re.search(text)


@pytest.mark.parametrize(
    "text",
    ["xxx" + "@qq.com", "your_gmail" + "@gmail.com", "example" + "@163.com"],
)
def test_pii_guard_has_documented_placeholders(pii_re, text: str) -> None:
    """Placeholders are documentation. The workflow filters them separately."""
    assert pii_re.search(text), "the pattern should match, then the allowlist filters it"
    allow = re.search(r"ALLOW='([^']+)'", ci_text())
    assert allow is not None, "ALLOW list missing from the PII guard"
    assert re.search(allow.group(1), text), f"{text!r} should be allowlisted"


# =============================== structural sanity ===============================
def test_ci_runs_the_provenance_guard() -> None:
    text = ci_text()
    assert "tests/contract/test_source_coverage.py" in text
    assert "build_registry.py" in text, "the registry reproducibility check must run"


def test_workflows_are_valid_yaml() -> None:
    import yaml

    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "jobs" in doc and doc["jobs"], f"{path.name} has no jobs"
        # `on` is parsed as the boolean True by YAML 1.1 parsers; either spelling is fine
        # so long as a trigger exists.
        assert ("on" in doc) or (True in doc), f"{path.name} has no trigger"


def test_action_versions_are_not_ancient() -> None:
    """Inherited v3/v4 references were three majors behind and about to stop working.

    Artifact upload/download in particular are only guaranteed compatible within a
    generation, so a mismatched pair is worse than an old pair.
    """
    required_major = {
        "actions/checkout": 5,
        "actions/setup-python": 5,
        "actions/upload-artifact": 5,
        "actions/download-artifact": 5,
        "actions/upload-pages-artifact": 4,
        "actions/deploy-pages": 4,
    }
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        for action, minimum in required_major.items():
            for match in re.finditer(rf"{re.escape(action)}@v(\d+)", text):
                major = int(match.group(1))
                assert major >= minimum, (
                    f"{path.name}: {action}@v{major} is behind v{minimum}; "
                    "run the bump check against the releases API"
                )
