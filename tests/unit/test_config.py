"""Config loading, env overrides, and secret redaction."""

from __future__ import annotations

from pathlib import Path

import pytest

from aidaily.config import (
    AppConfig,
    ConfigError,
    apply_env_overrides,
    load_config,
    load_secrets,
    redact,
    validate_critical_sources,
    validate_delivery,
)

ROOT = Path(__file__).resolve().parents[2]
DAILY = ROOT / "config" / "daily.yaml"


def test_shipped_config_is_valid() -> None:
    """The committed config must always load -- CI fails otherwise."""
    cfg = load_config(DAILY, env={})
    assert cfg.timezone == "Asia/Shanghai"
    assert cfg.run.at_time().hour == 10, "北京时间 10:00 是既定决策"
    assert cfg.output.brief.enabled and cfg.output.deep.enabled
    assert cfg.output.deep.languages == ["zh"], "深度版默认纯中文（免费额度约束）"


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    """extra='forbid' everywhere: a typo'd knob must fail loudly, not be ignored."""
    bad = tmp_path / "daily.yaml"
    bad.write_text("timezone: UTC\nrun:\n  at: '10:00'\n  typo_knob: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid config"):
        load_config(bad, env={})


def test_bad_time_format_rejected() -> None:
    with pytest.raises(ConfigError, match=r"HH:MM|invalid config"):
        load_config(DAILY, env={"AIDAILY_RUN__AT": "25:99"})


def test_bad_timezone_rejected() -> None:
    with pytest.raises(ConfigError, match="unknown timezone"):
        load_config(DAILY, env={"AIDAILY_TIMEZONE": "Mars/Olympus"})


def test_missing_file() -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(Path("/nonexistent/daily.yaml"), env={})


# --- env overrides ---------------------------------------------------------------
def test_env_override_nested_ints_and_bools() -> None:
    cfg = load_config(
        DAILY,
        env={
            "AIDAILY_RUN__WINDOW_HOURS": "30",
            "AIDAILY_DELIVERY__EMAIL": "false",
            "AIDAILY_DEDUP__L2__SIMHASH_DISTANCE": "5",
        },
    )
    assert cfg.run.window_hours == 30
    assert cfg.delivery.email is False
    assert cfg.dedup.l2.simhash_distance == 5


def test_env_override_lists() -> None:
    cfg = load_config(DAILY, env={"AIDAILY_RUN__CRITICAL_SOURCES": "rss:a,rss:b"})
    assert cfg.run.critical_sources == ["rss:a", "rss:b"]


def test_env_override_does_not_mutate_the_source_mapping() -> None:
    data = {"run": {"window_hours": 26}}
    apply_env_overrides(data, {"AIDAILY_RUN__WINDOW_HOURS": "30"})
    assert data["run"]["window_hours"] == 26, "the caller's mapping must be left alone"


def test_unrelated_env_is_ignored() -> None:
    cfg = load_config(DAILY, env={"PATH": "/usr/bin", "GEMINI_API_KEY": "secret-value-here"})
    assert cfg.run.at == "10:00"


# --- critical sources validation --------------------------------------------------
def test_unknown_critical_source_is_a_hard_error() -> None:
    """A typo here would silently disable the freshness gate."""
    cfg = load_config(DAILY, env={})
    with pytest.raises(ConfigError, match="freshness gate"):
        validate_critical_sources(cfg, {"rss:something-else"})


def test_critical_sources_match_the_real_registry() -> None:
    import yaml

    cfg = load_config(DAILY, env={})
    reg = yaml.safe_load((ROOT / "sources" / "registry.yaml").read_text(encoding="utf-8"))
    ids = {s["source_id"] for s in reg["sources"]}
    validate_critical_sources(cfg, ids)  # must not raise


# --- secrets ---------------------------------------------------------------------
def test_secrets_are_collected_but_never_required() -> None:
    assert load_secrets({}) == {}
    got = load_secrets({"GEMINI_API_KEY": "abc", "PATH": "/bin"})
    assert got == {"GEMINI_API_KEY": "abc"}


def test_redact_removes_secret_values_from_text() -> None:
    env = {"SMTP_PASSWORD": "supersecretpassword", "TELEGRAM_BOT_TOKEN": "123456:AAHfake-token-value"}
    text = "connecting with supersecretpassword and 123456:AAHfake-token-value now"
    cleaned = redact(text, env)
    assert "supersecretpassword" not in cleaned
    assert "123456:AAHfake-token-value" not in cleaned
    assert cleaned.count("***") == 2


def test_redact_ignores_short_values_to_avoid_mangling_text() -> None:
    """A 3-char value would match inside ordinary words; redaction must not corrupt output."""
    assert redact("the cat sat", {"SMTP_HOST": "cat"}) == "the cat sat"


def test_delivery_warnings_when_credentials_absent() -> None:
    cfg = load_config(DAILY, env={})
    warnings = validate_delivery(cfg, env={})
    joined = " ".join(warnings)
    assert "SMTP" in joined
    assert "TELEGRAM_BOT_TOKEN" in joined
    assert "N8N_WEBHOOK_URL" in joined
    assert "R2" in joined


def test_delivery_warnings_clear_when_credentials_present() -> None:
    cfg = load_config(DAILY, env={})
    env = {
        "SMTP_HOST": "smtp.qq.com", "SMTP_PASSWORD": "x",
        "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c",
        "N8N_WEBHOOK_URL": "https://n8n.example/hook",
        "R2_ACCESS_KEY_ID": "k",
    }
    assert validate_delivery(cfg, env=env) == []
