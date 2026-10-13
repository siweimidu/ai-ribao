"""Unified LLM layer: one transport, one error taxonomy, tiers and a spending cap."""

from .client import (
    AuthError,
    BudgetExceeded,
    LLMError,
    LLMResponse,
    LLMUnavailable,
    OpenAICompatClient,
    ProviderError,
    ProviderSpec,
    RateLimited,
    UnsupportedParam,
    extract_json,
)
from .router import (
    OFFICIAL_FREE_DEFAULTS,
    TIER_RANK,
    Budget,
    Router,
    RouterStats,
    providers_from_env,
)

__all__ = [
    "AuthError",
    "Budget",
    "BudgetExceeded",
    "LLMError",
    "LLMResponse",
    "LLMUnavailable",
    "OFFICIAL_FREE_DEFAULTS",
    "OpenAICompatClient",
    "ProviderError",
    "ProviderSpec",
    "RateLimited",
    "Router",
    "RouterStats",
    "TIER_RANK",
    "UnsupportedParam",
    "extract_json",
    "providers_from_env",
]
