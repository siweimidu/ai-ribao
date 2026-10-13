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
    # `git grep -E` uses POSIX ERE, which has no lookarounds. The workflow's own comment
    # says the lookbehind is load-bearing, so this test would fail loudly if someone
    # dropped it -- which is exactly the intent.
    return re.compile(patterns[0])


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


@pytest.mark.parametrize(
    "text",
    [
        "sk-proj-" + "A" * 40,
        "gsk_" + "a" * 40,
        "ghp_" + "A" * 36,
        "github_pat_" + "A" * 30,
        "cfat_" + "A" * 30,
        "AKIAIOSFODNN7EXAMPLE",
        "nvapi-" + "A" * 30,
        "key = sk-" + "x9" * 20,
        "token:gsk_" + "Z" * 32,
    ],
)
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


# =============================== PII =============================================
@pytest.mark.parametrize(
    "text",
    ["real.person@gmail.com", "2166075979@qq.com", "someone@163.com", "x@outlook.com"],
)
def test_pii_guard_fires_on_personal_addresses(pii_re, text: str) -> None:
    assert pii_re.search(text)


@pytest.mark.parametrize(
    "text",
    ["xxx@qq.com", "your_gmail@gmail.com", "example@163.com"],
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
