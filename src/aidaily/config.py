"""Configuration loading, validation, and secret handling.

Split by sensitivity, because mixing the two is how keys end up in git:

* `config/daily.yaml`  -- non-secret behaviour (schedule, thresholds, delivery toggles).
                           Safe to commit, safe to print in a bug report.
* environment variables -- secrets (API keys, SMTP password). Never written to disk by
                           this project, never echoed in logs, never placed in output.

Environment overrides use `AIDAILY_` with `__` for nesting:
    AIDAILY_RUN__WINDOW_HOURS=30      -> run.window_hours = 30
    AIDAILY_DELIVERY__EMAIL=false     -> delivery.email = False
Types are coerced from the existing value, so YAML stays the source of truth for shape.
"""

from __future__ import annotations

import os
import re
from datetime import time
from pathlib import Path
from typing import Any, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "daily.yaml"

ENV_PREFIX = "AIDAILY_"
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class ConfigError(RuntimeError):
    pass


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    at: str = "04:00"
    window_hours: int = 26
    critical_wait_minutes: int = 20
    critical_sources: list[str] = Field(default_factory=list)
    #: Every hour the workflow collects at, in `timezone`. The first entry is the day's first
    #: collection and is what `at` must equal; the rest are the later slots. Kept as data because
    #: two places need it and they must agree: the "too early to publish" gate and the
    #: critical-source wait window. Hard-coding "07:00" in the wait logic left the evening run
    #: waiting for nothing.
    #: Three slots. Measured with the old 07:00/19:00 pair: a story that broke at 15:00 Beijing
    #: was still missing from the 19:00 issue, because that run closed its window at 14:38 UTC
    #: (22:38 Beijing) -- the afternoon burst landed after the cut. 04:00 / 12:00 / 20:00 gives
    #: the day three chances, four hours apart at the tightest.
    slots: list[str] = Field(default_factory=lambda: ["04:00", "12:00", "20:00"])

    def publish_hour(self) -> int:
        """Hour of the day's first collection.

        The "too early" gate needs it. `__main__` used to read
        `cfg.run.publish_hour if hasattr(cfg.run, "publish_hour") else 7` -- there is no such
        *field*, so the probe was always False and the gate always used 7. Deriving the value
        from `at` keeps the gate and the cron from disagreeing when the schedule moves.
        """
        return self.at_time().hour

    def at_time(self) -> time:
        m = _HHMM.match(self.at.strip())
        if not m:
            raise ConfigError(f"run.at must be HH:MM, got {self.at!r}")
        return time(int(m.group(1)), int(m.group(2)))

    def schedule_times(self) -> list[time]:
        """Every slot as a `time`, in order, with `at` guaranteed present."""
        out: list[time] = []
        for raw in self.slots or [self.at]:
            m = _HHMM.match(str(raw).strip())
            if not m:
                raise ConfigError(f"run.slots entries must be HH:MM, got {raw!r}")
            out.append(time(int(m.group(1)), int(m.group(2))))
        if self.at_time() not in out:
            out.insert(0, self.at_time())
        return sorted(out)


class OutputVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    max_items: int = 15
    languages: list[str] = Field(default_factory=lambda: ["zh"])
    english_on_demand: bool = False


class OutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief: OutputVariant = OutputVariant()
    deep: OutputVariant = OutputVariant(max_items=60)


class L2Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    simhash_distance: int = 3
    title_similarity_merge: float = 0.85
    title_similarity_ambiguous: float = 0.92
    publish_window_hours: int = 72
    ambiguous_window_hours: int = 24


class L3Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    candidate_limit: int = 150
    #: how many candidate clusters may be sent to the model. Each one costs a call, so
    #: this is the main lever on both the bill and the wall-clock time of a run.
    max_clusters: int = 60
    judge_concurrency: int = 4
    entity_overlap_min: int = 2
    time_bucket_hours: int = 6
    confidence_threshold: float = 0.75
    cross_day_window_days: int = 7


class DedupConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    l2: L2Config = L2Config()
    l3: L3Config = L3Config()


class QualityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_content_chars: int = 200
    source_weights: dict[str, float] = Field(default_factory=dict)

    # --- ranking (see src/aidaily/rank.py for why each one exists) -----------------
    #: hours after which an entry's recency term halves
    recency_half_life_hours: float = 12.0
    #: an old entry keeps this fraction of its score. Without a floor, decay alone
    #: re-creates the pure-recency ranking that put one source's seven angles on one
    #: topic at the top of the digest.
    recency_floor: float = 0.25
    #: how much each extra independent source is worth
    corroboration: float = 0.35
    #: how much a real body of text is worth; an entry that is only a headline cannot
    #: produce facts ("Title: New Apple TV 4K" / "Points: 153")
    content_substance: float = 0.45
    #: secondary signal: points, upvotes, likes
    engagement: float = 0.20
    #: diversity caps -- ranking alone cannot fix homogeneity when a few prolific feeds
    #: supply most of the candidates
    max_per_source: int = 2
    max_per_group: int = 3
    #: multiply the score of an entry whose title closely matches one already selected
    topic_similarity_penalty: float = 0.35
    topic_similarity_threshold: float = 0.55
    #: shared entities that count as "the same topic". Two is the smallest number that
    #: means something: one shared entity is usually just "Google".
    topic_overlap_min: int = 2
    topic_overlap_penalty: float = 0.45
    #: heavier penalty when the shared topic also shares a URL -- the same article, not a
    #: second source reporting it
    duplicate_url_penalty: float = 0.10
    #: The bar a story must clear, by source tier. Tiers are derived from the source category
    #: (`tiers.py`); these numbers are what each tier must score.
    #:
    #: A multiplier cannot separate two stories that are close; a threshold can. Defaults are
    #: calibrated on 112 archived events -- the model scores cluster at 70, so the three tiers
    #: straddle it. Re-measure with `scripts/calibrate.py` after changing the scoring prompt.
    tier_thresholds: dict[str, float] = Field(
        default_factory=lambda: {"T1": 65.0, "T1_5": 70.0, "T2": 75.0}
    )
    #: Independent scoring passes per batch, averaged. One call is a single sample of a noisy
    #: judgement, and the gap between passes is itself informative.
    score_passes: int = 2


class DeliveryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: bool = True
    telegram: bool = True
    rss: bool = True
    n8n: bool = True
    pages: bool = True


class StorageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cold: str = "r2"
    r2_optional: bool = True
    content_retention_days: int = 30
    monthly_shard_compression: str = "zstd"


class LLMBatchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summarize: int = 8
    cluster_judge: int = 10
    #: Headlines per rubric call. Larger than the other two because the rubric prompt is
    #: short per item -- an id and a title -- and because the point of batching is to bring
    #: a full ranking pass down from ~60 calls to under ten.
    rubric: int = 10
    #: Concurrent rubric calls. Deliberately low: these run before anything is published, so
    #: a rate limit here delays the whole run rather than degrading a single item.
    rubric_concurrency: int = 2


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tiers: list[str] = Field(default_factory=lambda: ["official-free", "relay"])
    max_calls_per_run: int = 400
    max_tokens_per_run: int = 2_000_000
    relay_max_calls_per_run: int = 20
    request_timeout_s: int = 120
    batch_size: LLMBatchConfig = LLMBatchConfig()


class BudgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    on_exceed: str = "degrade_to_rules"


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: str = "Asia/Shanghai"
    run: RunConfig = RunConfig()
    output: OutputConfig = OutputConfig()
    dedup: DedupConfig = DedupConfig()
    quality: QualityConfig = QualityConfig()
    delivery: DeliveryConfig = DeliveryConfig()
    storage: StorageConfig = StorageConfig()
    llm: LLMConfig = LLMConfig()
    budget: BudgetConfig = BudgetConfig()


# --- secret handling -------------------------------------------------------------
SECRET_ENV_VARS = (
    "GEMINI_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY", "SAMBANOVA_API_KEY",
    "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY", "DASHSCOPE_API_KEY",
    "ZHIPU_API_KEY", "RELAY_KEYS_JSON",
    "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "MAIL_TO",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "N8N_WEBHOOK_URL",
    "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT", "R2_BUCKET",
    "PRODUCT_HUNT_TOKEN", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "FOLO_COOKIE",
    "TAVILY_API_KEY", "LWN_KEY", "GITHUB_TOKEN",
)
# Vars that are configuration, not secrets: they may appear in logs and reports.
NON_SECRET_ENV_VARS = ("GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_REF_NAME")


def load_secrets(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Collect only the secrets that are actually present. Never logs anything."""
    env = env if env is not None else os.environ
    return {k: env[k] for k in SECRET_ENV_VARS if env.get(k)}


def redact(text: str, env: Mapping[str, str] | None = None) -> str:
    """Replace every secret value with `***` so a log line can never leak one.

    Called on any string that might be logged or written into a digest. Cheap enough
    to apply unconditionally.
    """
    env = env if env is not None else os.environ
    out = text
    for value in load_secrets(env).values():
        if len(value) >= 8:            # short values would over-match and mangle text
            out = out.replace(value, "***")
    return out


# --- loading ---------------------------------------------------------------------
def _coerce(raw: str, current: Any) -> Any:
    if isinstance(current, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(current, int):
        return int(raw)
    if isinstance(current, float):
        return float(raw)
    if isinstance(current, list):
        return [x.strip() for x in raw.split(",") if x.strip()]
    return raw


def apply_env_overrides(data: dict, env: Mapping[str, str]) -> dict:
    """Apply AIDAILY_A__B=value onto the parsed YAML mapping (in place, on a copy)."""
    import copy

    data = copy.deepcopy(data)
    for key, raw in env.items():
        if not key.startswith(ENV_PREFIX):
            continue
        path = key[len(ENV_PREFIX):].lower().split("__")
        node = data
        for part in path[:-1]:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        leaf = path[-1]
        node[leaf] = _coerce(raw, node.get(leaf))
    return data


def load_config(
    path: Path | str = DEFAULT_CONFIG, env: Mapping[str, str] | None = None
) -> AppConfig:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"config root must be a mapping: {p}")

    env = env if env is not None else os.environ
    merged = apply_env_overrides(raw, env)
    try:
        cfg = AppConfig.model_validate(merged)
    except ValidationError as exc:
        raise ConfigError(f"invalid config {p}:\n{exc}") from exc

    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(cfg.timezone)
    except Exception as exc:  # noqa: BLE001
        raise ConfigError(f"unknown timezone {cfg.timezone!r}") from exc

    cfg.run.at_time()  # validates HH:MM
    return cfg


def validate_critical_sources(cfg: AppConfig, source_ids: set[str]) -> None:
    """A critical source that does not exist is a silent correctness hole.

    The wait gate would simply never wait, and the digest would ship stale content
    while claiming everything was fresh. So a bad id is a hard error.
    """
    unknown = [s for s in cfg.run.critical_sources if s not in source_ids]
    if unknown:
        raise ConfigError(
            "run.critical_sources references unknown source_id(s): "
            + ", ".join(unknown)
            + " -- fix the config or the registry; an unknown critical source would "
            "disable the freshness gate silently"
        )


def validate_delivery(cfg: AppConfig, env: Mapping[str, str] | None = None) -> list[str]:
    """Report enabled delivery channels that have no credentials.

    Returns warnings rather than raising: a missing Telegram token should degrade to
    "no Telegram", not abort a run that could still publish the web digest.
    """
    env = env if env is not None else os.environ
    warnings: list[str] = []
    if cfg.delivery.email and not (env.get("SMTP_HOST") and env.get("SMTP_PASSWORD")):
        warnings.append("email 已启用但缺少 SMTP_HOST/SMTP_PASSWORD，本次将跳过邮件")
    if cfg.delivery.telegram and not (env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID")):
        warnings.append("telegram 已启用但缺少 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID，本次将跳过推送")
    if cfg.delivery.n8n and not env.get("N8N_WEBHOOK_URL"):
        warnings.append("n8n 已启用但缺少 N8N_WEBHOOK_URL，本次将跳过 webhook")
    if cfg.storage.cold == "r2" and not env.get("R2_ACCESS_KEY_ID"):
        if not cfg.storage.r2_optional:
            warnings.append("storage.cold=r2 但缺少 R2 凭证，且 r2_optional=false")
        else:
            warnings.append("R2 凭证缺失，冷存自动降级为本地（r2_optional=true）")
    return warnings
