"""LLM clients: one OpenAI-compatible implementation, plus a native Gemini path.

Deliberately built on `httpx` rather than a vendor SDK. The audited repositories show why:
each SDK brings its own retry policy, its own exception hierarchy and its own idea of
what "rate limited" means, and layering those made the fallback logic in `dailydawn` and
`daybrief` hard to reason about. One transport, one error taxonomy, one retry policy.

Every request an OpenAI-compatible provider gets looks the same; the only per-provider
knowledge is in `capabilities`, which the router uses to avoid sending a parameter the
provider will reject.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

import httpx

# --- error taxonomy --------------------------------------------------------------
# The router's whole strategy depends on telling these apart:
#   AuthError        -> the key is wrong/dead: stop using this provider for the run
#   RateLimited      -> either wait (transient) or abandon the provider (daily quota)
#   UnsupportedParam -> retry the same request without the offending parameter
#   ProviderError    -> anything else; try the next provider


class LLMError(Exception):
    pass


class AuthError(LLMError):
    """401/403: the credential is not usable. No point retrying."""


class RateLimited(LLMError):
    def __init__(self, message: str, *, daily: bool = False, retry_after: float | None = None) -> None:
        super().__init__(message)
        #: True when the provider says the quota is per-day, in which case waiting
        #: inside this run is pointless -- the provider is done for today.
        self.daily = daily
        self.retry_after = retry_after


class UnsupportedParam(LLMError):
    """The provider rejected a parameter such as `response_format`."""


class ProviderError(LLMError):
    """Anything else; the router tries the next provider.

    `permanent` marks failures that will not fix themselves within a run -- a retired
    model name, a removed route. They are still worth recording: during the first live
    run Gemini answered `404 This model is no longer available to new users` on every
    single call and the run simply reported "provider failed", which hid the real cause.
    """

    def __init__(self, message: str, *, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


class BudgetExceeded(LLMError):
    """The run's own spending cap was hit. Callers must degrade, not crash."""


class LLMUnavailable(LLMError):
    """Every provider failed. Callers must degrade, not crash."""


# --- provider description --------------------------------------------------------
@dataclass
class ProviderSpec:
    id: str
    tier: str                      # official-free | official-paid | relay
    base_url: str
    model: str
    key_env: str | None = None
    key_literal: str | None = None
    #: capabilities that change the request shape, e.g. {"json_object", "system_role"}
    capabilities: set[str] = field(default_factory=lambda: {"json_object", "system_role"})
    timeout_s: float = 120.0
    #: lower runs first inside a tier
    weight: int = 100
    #: Human label for the credential, from the key file's `label` field.
    #:
    #: For diagnosis only. With rotation across many keys, "relay:api.example.com#3 hit its
    #: daily cap" is actionable and "a relay failed" is not -- and this is how the operator
    #: knows *which* of their accounts to look at. Never holds a key or a hash of one.
    note: str | None = None

    #: True for models that spend completion tokens on hidden reasoning before writing an answer
    #: (`openai/gpt-oss-120b`, DeepSeek R-series, most "thinking" variants).
    #:
    #: Measured 2026-10-23 on Groq: `openai/gpt-oss-120b` with `max_tokens=8` returns
    #: content="" and finish_reason="length" while billing 83 tokens -- the whole budget went to
    #: reasoning and not one character of the answer was written. With `max_tokens=512` the same
    #: prompt answers "ok" in 109 tokens.
    #:
    #: The client already turns an empty completion into an error so the router can move on, but
    #: that spends a call to learn something the spec could have stated. With this flag the
    #: budget is raised before the request, not after it fails.
    reasoning: bool = False

    #: Floor applied to `max_tokens` when `reasoning` is set. From the measurement above: 512
    #: answered cleanly where 8 produced nothing, and the rubric already runs at 4000.
    reasoning_floor: int = 1024

    def resolve_key(self, env: Mapping[str, str]) -> str | None:
        if self.key_env and env.get(self.key_env):
            return env[self.key_env]
        return self.key_literal

    def redacted(self) -> str:
        return f"{self.id} ({self.tier}, {self.base_url})"


@dataclass
class LLMResponse:
    text: str
    provider_id: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    finish_reason: str = ""
    #: parameters dropped to make the provider accept the request
    degraded_params: list[str] = field(default_factory=list)


def extract_json(text: str) -> Any:
    """Parse JSON from a model reply, tolerating a markdown fence.

    Both audited implementations needed this (`_extract_json` in dailydawn), because
    models wrap JSON in ```json blocks often enough that failing on it is a real bug.
    """
    raw = (text or "").strip()
    if raw.startswith("```"):
        first_newline = raw.find("\n")
        if first_newline != -1:
            raw = raw[first_newline + 1:]
        if raw.rstrip().endswith("```"):
            raw = raw.rstrip()[:-3]
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost JSON span. The EARLIEST opener wins: trying "{" first
    # would turn `Result: [{"x": 1}] Done.` into the inner object instead of the array.
    spans: list[tuple[int, int]] = []
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = raw.find(opener), raw.rfind(closer)
        if start != -1 and end > start:
            spans.append((start, end))
    for start, end in sorted(spans):
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            continue
    raise LLMError(f"reply is not JSON: {raw[:120]!r}")


class OpenAICompatClient:
    """Chat Completions against any OpenAI-compatible endpoint."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    async def complete(
        self,
        spec: ProviderSpec,
        messages: list[dict[str, str]],
        *,
        key: str,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        json_mode: bool = False,
        drop_params: set[str] | None = None,
    ) -> LLMResponse:
        drop = drop_params or set()
        payload: dict[str, Any] = {"model": spec.model, "messages": messages, "temperature": temperature}
        if max_tokens is not None:
            # **A reasoning model needs room to think before it answers.**
            #
            # Measured on Groq 2026-10-23: `openai/gpt-oss-120b` with `max_tokens=8` billed 83
            # tokens and returned `content=""` with `finish_reason="length"` -- the budget went
            # entirely to hidden reasoning and the answer was never started. The same prompt at
            # 512 tokens answered "ok" in 109.
            #
            # The empty completion is caught downstream and turned into an error so the router
            # can try the next provider, but that costs a request to learn what the spec already
            # says. Raising the floor here means the first call succeeds.
            effective = max_tokens
            if spec.reasoning:
                effective = max(max_tokens, spec.reasoning_floor)
            payload["max_tokens"] = effective
        if json_mode and "json_object" in spec.capabilities and "response_format" not in drop:
            payload["response_format"] = {"type": "json_object"}
        if "system_role" not in spec.capabilities and messages and messages[0].get("role") == "system":
            # Some endpoints have no system role; fold it into the first user turn
            # rather than silently dropping the instructions.
            system = messages[0]["content"]
            rest = messages[1:]
            if rest:
                rest = [dict(rest[0]), *rest[1:]]
                rest[0]["content"] = f"{system}\n\n{rest[0]['content']}"
                payload["messages"] = rest
                drop = drop | {"system_role"}

        start = time.monotonic()
        try:
            resp = await self.http.post(
                f"{spec.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
                timeout=spec.timeout_s,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{spec.id}: {type(exc).__name__}: {exc}") from exc

        latency = int((time.monotonic() - start) * 1000)
        if resp.status_code in (401, 403):
            raise AuthError(f"{spec.id}: HTTP {resp.status_code}")
        if resp.status_code == 429:
            body = _safe_text(resp)
            raise RateLimited(
                f"{spec.id}: HTTP 429",
                daily=_looks_daily(body),
                retry_after=_retry_after(resp.headers.get("Retry-After")),
            )
        if resp.status_code == 400:
            body = _safe_text(resp)
            reason = _param_rejection(body)
            if reason:
                raise UnsupportedParam(f"{spec.id}: {reason}")
            raise ProviderError(f"{spec.id}: HTTP 400 {body[:160]}")
        if resp.status_code == 404:
            raise ProviderError(
                f"{spec.id}: HTTP 404 {_safe_text(resp)[:120]}", permanent=True
            )
        if resp.status_code >= 500:
            raise ProviderError(f"{spec.id}: HTTP {resp.status_code}")
        if resp.status_code != 200:
            raise ProviderError(f"{spec.id}: HTTP {resp.status_code} {_safe_text(resp)[:120]}")

        try:
            doc = resp.json()
        except ValueError as exc:
            raise ProviderError(f"{spec.id}: response is not JSON") from exc
        return _parse_completion(doc, spec, latency, sorted(drop))


def _parse_completion(doc: dict, spec: ProviderSpec, latency: int, dropped: list[str]) -> LLMResponse:
    choices = doc.get("choices") or []
    if not choices:
        raise ProviderError(f"{spec.id}: no choices in response")
    first = choices[0]
    message = first.get("message") or {}
    text = message.get("content")
    if text is None:
        # Some providers return `text` for completion-style responses.
        text = first.get("text") or ""
    text = str(text)
    finish_reason = str(first.get("finish_reason") or "")

    if not text.strip():
        # An empty completion is never useful for a summary or a JSON extraction, and it
        # is not always a provider fault: a reasoning model handed a small max_tokens
        # spends the whole budget on reasoning and returns nothing. Surfacing it as an
        # error lets the router try the next provider instead of shipping an empty
        # summary that looks like a successful call.
        raise ProviderError(
            f"{spec.id}: empty completion (finish_reason={finish_reason or 'unknown'}"
            f"{', max_tokens likely consumed by reasoning tokens' if finish_reason == 'length' else ''})"
        )

    usage = doc.get("usage") or {}
    return LLMResponse(
        text=text,
        provider_id=spec.id,
        model=str(doc.get("model") or spec.model),
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        latency_ms=latency,
        finish_reason=finish_reason,
        degraded_params=dropped,
    )


def _safe_text(resp: httpx.Response) -> str:
    try:
        return resp.text[:400]
    except Exception:  # noqa: BLE001
        return ""


#: 400 responses that mean "this parameter combination did not work" rather than
#: "this request is malformed". They must degrade the request, not kill the provider.
#:
#: The JSON-validation family was found the hard way: Groq answers a `response_format:
#: json_object` request whose generation failed validation with
#: `400 Failed to validate JSON. Please adjust your prompt.` -- a message containing
#: neither "response_format" nor "json_object", so the first classifier treated it as a
#: provider failure and abandoned a perfectly healthy provider.
_PARAM_REJECTION_MARKERS: tuple[tuple[str, str], ...] = (
    ("response_format", "response_format rejected"),
    ("json_object", "json_object mode rejected"),
    ("failed to validate json", "provider-side JSON validation failed"),
    ("failed_generation", "provider-side JSON validation failed"),
    ("json_validate_failed", "provider-side JSON validation failed"),
    ("system role", "system role rejected"),
    ("system message", "system message rejected"),
)


def _param_rejection(body: str) -> str | None:
    low = body.lower()
    for marker, reason in _PARAM_REJECTION_MARKERS:
        if marker in low:
            return reason
    return None


def _looks_daily(body: str) -> bool:
    """Distinguish a per-day quota from a short-term rate limit.

    dailydawn and daybrief both had to special-case this: a daily quota means retrying
    inside the run only wastes time, so the provider is dropped instead.
    """
    low = body.lower()
    return any(marker in low for marker in ("per day", "daily", "quota", "exceeded your current quota"))


def _retry_after(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except TypeError:
        return None
    except ValueError:
        return None
