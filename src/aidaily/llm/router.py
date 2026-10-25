"""Provider routing: tiers, fallback chain, and a hard spending cap.

This encodes the four reliability mechanisms the audited projects each discovered
separately, in one place:

* **fallback chain** (dailydawn: a model that hits its daily cap must not fail the run)
* **provider blacklisting** (daybrief: `mark_down` on "tokens per day", "绝不空等")
* **parameter degradation** (a provider that rejects `response_format` still gets to answer)
* **budget breaker** (new: a run may not spend more than it was allowed to)

Ordering is by tier, then weight. Tiers exist because trust is not uniform: an official
free tier has a published quota and terms, while many of the relay endpoints in the key
file are unattributed resellers. Relay providers therefore run last and are additionally
capped per run.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

import httpx

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

#: Provider families tried first, in this order. 「优先使用 Agnes 和 Groq」.
#:
#: Matched on **exact host**, not a substring of the whole spec. A substring test over
#: `f"{spec.id} {spec.base_url}"` looks harmless and is not: the test fixtures use
#: `https://groq.example/v1`, and a `"groq" in haystack` check promoted them ahead of the
#: provider the test was about, so five unrelated routing tests failed.
#:
#: Each entry is (substring of HOST, rank). Lower rank runs first.
_PREFERRED_HOSTS: tuple[tuple[str, int], ...] = (
    ("agnes-ai.com", 0),
    ("agnes-ai.cn", 0),
    ("api.groq.com", 1),
    ("groq.com", 1),
)

#: Ranks for everything not named above.
_RANK_OTHER_RELAY = 5
_RANK_OTHER_FIRST_PARTY = 9


def priority_of(spec) -> int:
    """Sort key: lower runs first.

    Only the **host** decides the family. `tier` breaks the remaining ties, because a relay
    key that is neither Agnes nor Groq still runs before the small first-party quotas.
    """
    host = (spec.base_url or "").split("//")[-1].split("/")[0].lower()
    for marker, rank in _PREFERRED_HOSTS:
        if host == marker or host.endswith("." + marker):
            return rank
    return _RANK_OTHER_RELAY if spec.tier == "relay" else _RANK_OTHER_FIRST_PARTY


TIER_RANK = {"official-free": 0, "official-paid": 1, "relay": 2}

#: Providers we have verified ourselves and that publish quotas/terms.
#: Model names matter more than they look: `gemini-2.5-flash-lite` started answering
#: `404 This model is no longer available to new users`, while the `-latest` alias kept
#: working. Prefer vendor aliases over pinned model ids for that reason.
OFFICIAL_FREE_DEFAULTS: tuple[tuple[str, str, str], ...] = (
    # (id, base_url, key env)
    ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    ("groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    ("cerebras", "https://api.cerebras.ai/v1", "CEREBRAS_API_KEY"),
    ("sambanova", "https://api.sambanova.ai/v1", "SAMBANOVA_API_KEY"),
    ("nvidia", "https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),
    ("mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    ("huggingface", "https://router.huggingface.co/v1", "HUGGINGFACE_API_KEY"),
    ("modelscope", "https://api-inference.modelscope.cn/v1", "MODELSCOPE_API_KEY"),
    ("openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
)


@dataclass
class Budget:
    max_calls: int = 400
    max_tokens: int = 2_000_000
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def exhausted(self) -> bool:
        return self.calls >= self.max_calls or self.tokens >= self.max_tokens

    def record(self, resp: LLMResponse) -> None:
        self.calls += 1
        self.prompt_tokens += resp.prompt_tokens
        self.completion_tokens += resp.completion_tokens

    def snapshot(self) -> dict[str, int]:
        return {
            "calls": self.calls, "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens, "tokens": self.tokens,
            "max_calls": self.max_calls, "max_tokens": self.max_tokens,
        }


@dataclass
class RouterStats:
    dead: dict[str, str] = field(default_factory=dict)      # provider id -> reason
    used: dict[str, int] = field(default_factory=dict)      # provider id -> calls
    #: last error per provider, including non-fatal ones. Without this a provider that
    #: failed every call with a retired model name recorded nothing at all.
    failures: dict[str, str] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def note(self, event: str, **kw: Any) -> None:
        self.events.append({"at": datetime.now(timezone.utc).isoformat(), "event": event, **kw})


class Router:
    def __init__(
        self,
        providers: list[ProviderSpec],
        http: httpx.AsyncClient,
        budget: Budget | None = None,
        *,
        env: Mapping[str, str] | None = None,
        relay_max_calls: int = 20,
        on_retry: Callable[[RateLimited], None] | None = None,
        rate_limit_backoff: float = 2.0,
        rate_limit_backoff_max: float = 30.0,
    ) -> None:
        self.env = env if env is not None else os.environ
        self.providers = sorted(
            providers, key=lambda p: (TIER_RANK.get(p.tier, 9), p.weight, p.id)
        )
        self.client = OpenAICompatClient(http)
        self.budget = budget or Budget()
        self.stats = RouterStats()
        self.relay_max_calls = relay_max_calls
        self._relay_calls = 0
        self._rr = 0
        self._lock = asyncio.Lock()
        self._on_retry = on_retry
        self._rate_limit_backoff = rate_limit_backoff
        self._rate_limit_backoff_max = rate_limit_backoff_max

    # --- provider bookkeeping ---------------------------------------------------
    def mark_dead(self, provider_id: str, reason: str) -> None:
        if provider_id not in self.stats.dead:
            self.stats.dead[provider_id] = reason
            self.stats.note("provider_dead", provider=provider_id, reason=reason)

    def available(self) -> list[ProviderSpec]:
        """Providers to try, ordered so the load spreads across every relay key.

        **Round-robin, not list order.**

        The list used to be returned in declaration order, so every call started at the first
        relay key and only advanced when it died. Measured 2026-10-25: relay #0 took 57 calls,
        #1 took 25, #2 took 15, #3 took 4 -- and #4 through #22 were never touched at all. Then
        #0, #1 and #2 all answered HTTP 429 at once, every groq key was already 429, and the
        router raised `LLMUnavailable`. 81 of 120 events fell back to rule-based excerpts while
        19 unused relay keys sat in the pool and the budget sat at 39% of its call cap.

        Rotating the starting offset spreads the same number of calls across every key, which
        is both fairer to each quota and much later to hit the point where all of them are
        rate-limited simultaneously.
        """
        out: list[ProviderSpec] = []
        for spec in self.providers:
            if spec.id in self.stats.dead:
                continue
            if spec.tier == "relay" and self._relay_calls >= self.relay_max_calls:
                continue
            if spec.resolve_key(self.env) is None:
                continue
            out.append(spec)

        if len(out) < 2:
            return out

        # **Preferred families first, rotation inside each family.**
        #
        # Two problems, fixed together:
        #
        # 1. *Order.* Every call started at declaration position, so the relay tier always
        #    began at `#0`. Measured 2026-10-25: 57 / 25 / 15 / 4 calls across the first four
        #    relay keys and **zero** for the other nineteen. Then #0, #1 and #2 all answered
        #    429 together, every groq key was already 429, and 81 of 120 events fell back to
        #    rule-based excerpts with 19 unused keys and 61% of budget left.
        #
        # 2. *Preference.* 「优先使用 Agnes 和 Groq」. `priority_of` ranks Agnes first, Groq
        #    second, other relays next, the remaining first-party keys last.
        #
        # Rotation happens among providers of equal priority only, so load spreads across the
        # Agnes keys without letting a lower-priority family jump the queue.
        buckets: dict[int, list[ProviderSpec]] = {}
        for spec in out:
            buckets.setdefault(priority_of(spec), []).append(spec)

        ordered: list[ProviderSpec] = []
        for rank in sorted(buckets):
            members = buckets[rank]
            if len(members) > 1:
                offset = self._rr % len(members)
                members = members[offset:] + members[:offset]
            ordered.extend(members)
        self._rr += 1
        return ordered

    # --- the one entry point ----------------------------------------------------
    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        json_mode: bool = False,
        purpose: str = "",
    ) -> LLMResponse:
        if self.budget.exhausted():
            raise BudgetExceeded(
                f"budget exhausted: {self.budget.calls}/{self.budget.max_calls} calls, "
                f"{self.budget.tokens}/{self.budget.max_tokens} tokens"
            )

        candidates = self.available()
        if not candidates:
            raise LLMUnavailable("no usable provider (all dead, missing keys, or relay cap reached)")

        last_error: Exception | None = None
        for spec in candidates:
            key = spec.resolve_key(self.env)
            if key is None:
                continue
            drop: set[str] = set()
            for attempt in (1, 2):
                try:
                    resp = await self.client.complete(
                        spec, messages, key=key, temperature=temperature,
                        max_tokens=max_tokens, json_mode=json_mode, drop_params=drop,
                    )
                except AuthError as exc:
                    self.mark_dead(spec.id, f"auth: {exc}")
                    last_error = exc
                    break
                except RateLimited as exc:
                    # Two different things were being treated as one.
                    #
                    # A **daily** cap means the provider is finished until tomorrow, and
                    # waiting is pointless. A **transient** 429 means "slow down" -- the
                    # provider is fine and will answer the next request.
                    #
                    # Marking both dead ended the run's use of that provider on its first
                    # transient 429. Measured against the relay endpoint: fifty calls
                    # succeeded, the fifty-first hit a momentary limit, the provider was
                    # marked dead, and the remaining 47 of 60 events fell back to rule-based
                    # English summaries. Probing the same endpoint immediately afterwards
                    # answered eight consecutive requests in about a second each -- the
                    # credential was never exhausted; the router simply stopped using it.
                    if exc.daily:
                        self.mark_dead(spec.id, f"rate_limited(daily=True): {exc}")
                        last_error = exc
                        break

                    if attempt == 1:
                        delay = exc.retry_after if exc.retry_after else self._rate_limit_backoff
                        # Cap it: a provider that asks for ten minutes is not worth the
                        # job's time budget, and the next candidate should get a turn.
                        delay = min(float(delay), self._rate_limit_backoff_max)
                        self.stats.note("rate_limited_retry", provider=spec.id,
                                        wait_s=round(delay, 1), error=str(exc)[:120])
                        if self._on_retry:
                            self._on_retry(exc)
                        await asyncio.sleep(delay)
                        continue

                    # Still limited after waiting: stop using it for this run, but record it
                    # as unavailable rather than dead, because the credential is fine.
                    self.stats.failures[spec.id] = f"rate_limited: {exc}"[:200]
                    last_error = exc
                    break
                except UnsupportedParam as exc:
                    if attempt == 1:
                        # Retry the same provider once with the parameter removed: a
                        # provider that cannot do JSON mode can still answer in prose.
                        drop = drop | ({"response_format"} if json_mode else {"system_role"})
                        self.stats.note("degrade_params", provider=spec.id, dropped=sorted(drop), error=str(exc))
                        continue
                    last_error = exc
                    break
                except ProviderError as exc:
                    self.stats.failures[spec.id] = str(exc)[:200]
                    self.stats.note("provider_error", provider=spec.id, error=str(exc)[:200],
                                    permanent=getattr(exc, "permanent", False))
                    if getattr(exc, "permanent", False):
                        # A retired model name will not start working mid-run.
                        self.mark_dead(spec.id, f"permanent: {exc}")
                    last_error = exc
                    break
                else:
                    async with self._lock:
                        self.budget.record(resp)
                        self.stats.used[spec.id] = self.stats.used.get(spec.id, 0) + 1
                        if spec.tier == "relay":
                            self._relay_calls += 1
                    self.stats.note(
                        "call", provider=spec.id, model=resp.model, purpose=purpose,
                        prompt_tokens=resp.prompt_tokens, completion_tokens=resp.completion_tokens,
                        latency_ms=resp.latency_ms, degraded=resp.degraded_params,
                    )
                    return resp
        raise LLMUnavailable(f"all providers failed: {last_error}")

    async def complete_json(self, messages: list[dict[str, str]], **kw: Any) -> Any:
        """Complete and parse JSON, with one repair attempt.

        A model that emits prose around the JSON is common enough that failing the whole
        item would be wasteful; the repair turn is far cheaper than the original call.
        """
        resp = await self.complete(messages, json_mode=True, **kw)
        try:
            return extract_json(resp.text)
        except LLMError:
            repair = [
                *messages,
                {"role": "assistant", "content": resp.text[:2000]},
                {"role": "user", "content": "只输出合法 JSON，不要任何解释或 markdown 代码块。"},
            ]
            # Override rather than pass a second keyword: callers routinely supply
            # `temperature`, and `f(temperature=..., **kw)` raises when kw has it too.
            repair_kw = {**kw, "temperature": 0.0}
            resp2 = await self.complete(repair, json_mode=True, **repair_kw)
            return extract_json(resp2.text)


# --- building a router from the environment --------------------------------------
#: Model-name fragments that mark a reasoning model -- one that spends completion tokens on
#: hidden thinking before writing an answer.
#:
#: Measured on Groq 2026-10-23: `openai/gpt-oss-120b` at `max_tokens=8` billed 83 tokens and
#: returned an empty string with `finish_reason="length"`; at 512 the same prompt answered.
#: `deepseek-r1`, `o1`, `o3` and the Qwen `qwq` line behave the same way.
#:
#: Matched as a substring on the lower-cased model id, because providers spell these names with
#: a vendor prefix (`openai/gpt-oss-120b`, `moonshotai/kimi-k2-thinking`) and a suffix
#: (`...-0905`). An exact-name table would miss every variant.
_REASONING_MARKERS = (
    "gpt-oss",          # both 20b and 120b think before answering
    "deepseek-r",
    "-r1",
    "qwq",
    "thinking",
    "reasoning",
    "o1-", "o1/", "o3-", "o3/", "o4-",
)


def is_reasoning_model(model: str) -> bool:
    """True when this model needs a larger `max_tokens` to produce any answer at all.

    The failure this prevents is not a bad answer, it is **no answer**: the budget is consumed
    by reasoning and `content` comes back empty, which downstream looks like a dead provider.
    """
    lowered = (model or "").lower()
    return any(marker in lowered for marker in _REASONING_MARKERS)

def providers_from_env(
    env: Mapping[str, str] | None = None,
    *,
    default_model: str = "gemini-flash-lite-latest",
    include_relay: bool = True,
) -> list[ProviderSpec]:
    """Assemble the provider list from environment variables only.

    Keys are read from the environment and never from a config file: that is the whole
    point of the split in `config.py`. `RELAY_KEYS_JSON` (a GitHub Secret) carries the
    relay tier as a JSON array of `{"baseUrl": ..., "key": ..., "label": ...}`.
    """
    env = env if env is not None else os.environ
    out: list[ProviderSpec] = []

    model_env = {
        "gemini": "GEMINI_MODEL", "groq": "GROQ_MODEL", "cerebras": "CEREBRAS_MODEL",
        "mistral": "MISTRAL_MODEL", "openrouter": "OPENROUTER_MODEL",
    }
    for idx, (pid, base, key_env) in enumerate(OFFICIAL_FREE_DEFAULTS):
        if not env.get(key_env):
            continue
        out.append(
            ProviderSpec(
                id=pid, tier="official-free", base_url=base,
                model=env.get(model_env.get(pid, ""), default_model),
                key_env=key_env, weight=idx,
            )
        )

    if include_relay and env.get("RELAY_KEYS_JSON"):
        try:
            rows = json.loads(env["RELAY_KEYS_JSON"])
        except (TypeError, ValueError):
            rows = []

        # Every key is kept, including several for the same host.
        #
        # This used to dedupe on `baseUrl` alone (`if base in seen: continue`), so a host
        # with thirteen keys contributed exactly one provider and the other twelve were
        # discarded before the router ever saw them. The user hit this directly: "我一个密钥
        # 的免费额度耗完不能自动切下一个" -- which is precisely what the dedupe caused.
        #
        # The measured key file has 13 keys for `api.hcnsec.cn` and 3 for `open.bigmodel.cn`,
        # so rotation within a host is the normal case rather than an edge case.
        #
        # Provider ids must be unique per key, not per host, because a daily-limited key is
        # recorded dead by id -- with one id per host, exhausting any single key retired all
        # thirteen.
        per_host: dict[str, int] = {}
        for row in rows if isinstance(rows, list) else []:
            base = str(row.get("baseUrl") or "").rstrip("/")
            key = str(row.get("key") or "")
            if not base or not key:
                continue
            host = base.split("//")[-1].split("/")[0]
            index = per_host.get(host, 0)
            per_host[host] = index + 1
            label = str(row.get("label") or "").strip()
            model = str(row.get("model") or default_model)
            out.append(
                ProviderSpec(
                    # `#n` rather than a hash of the key: a stable, readable position, and
                    # no fingerprint of a credential in a log line or a stats dict.
                    id=f"relay:{host}#{index}",
                    tier="relay", base_url=base,
                    model=model,
                    key_literal=key, weight=len(out),
                    note=label or None,
                    reasoning=is_reasoning_model(model),
                )
            )
    return out
