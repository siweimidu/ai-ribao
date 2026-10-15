"""The relay payload must be read, or the reason must be visible.

`providers_from_env` swallows a `json.JSONDecodeError` and returns no relay providers. That
is the right call for a library -- it has no way to report -- but it makes the *caller*
responsible for saying something, and the caller was not. The result was the failure this
project keeps re-learning: the secret was configured, the environment variable arrived, the
JSON did not parse, and the only symptom was a digest that degraded to English with two
providers instead of a hundred.

A GitHub secret stored through a shell pipeline can arrive UTF-16 encoded or with a BOM, so
"it is set" is not the same as "it is readable" -- which is what these tests pin down.
"""

from __future__ import annotations

import argparse
import json

from aidaily.__main__ import _build_router


def make_args(**over):
    base = {"no_llm": False, "relay_keys": None}
    base.update(over)
    return argparse.Namespace(**base)


def test_a_well_formed_payload_builds_relay_providers(monkeypatch) -> None:
    payload = json.dumps([
        {"baseUrl": "https://a.example/v1", "key": "k1", "model": "m1"},
        {"baseUrl": "https://a.example/v1", "key": "k2", "model": "m1"},
    ])
    monkeypatch.setenv("RELAY_KEYS_JSON", payload)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    router, warnings, http = _build_router(make_args())
    try:
        assert router is not None
        # Both keys on the host, which is the rotation requirement.
        assert len(router.providers) == 2
        assert any("2 条" in w for w in warnings)
    finally:
        if http is not None:
            # syncio.run, not get_event_loop().run_until_complete. The latter works when
            # this file runs alone and raises RuntimeError: There is no current event loop
            # once an earlier test in the same session has closed the loop -- so the test
            # passed in isolation and failed in CI, which is the worst way to be wrong.
            import asyncio

            asyncio.run(http.aclose())


def test_a_leading_bom_is_tolerated(monkeypatch) -> None:
    """A BOM is an encoding artefact, not a reason to refuse a working credential."""
    payload = "\ufeff" + json.dumps(
        [{"baseUrl": "https://a.example/v1", "key": "k1", "model": "m1"}]
    )
    monkeypatch.setenv("RELAY_KEYS_JSON", payload)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    router, warnings, http = _build_router(make_args())
    try:
        assert router is not None, "带 BOM 的密钥必须可用"
        assert len(router.providers) == 1
    finally:
        if http is not None:
            # syncio.run, not get_event_loop().run_until_complete. The latter works when
            # this file runs alone and raises RuntimeError: There is no current event loop
            # once an earlier test in the same session has closed the loop -- so the test
            # passed in isolation and failed in CI, which is the worst way to be wrong.
            import asyncio

            asyncio.run(http.aclose())


def test_an_unreadable_payload_says_so(monkeypatch) -> None:
    """The whole point: a broken payload must produce a warning, not silence.

    A truncated secret is the realistic case -- a shell pipeline or a paste that lost its
    tail. (A UTF-16 payload cannot be used here: a NUL byte cannot be stored in an
    environment variable at all, so that failure mode is unreachable rather than untested.)
    """
    full = json.dumps([{"baseUrl": "https://a.example/v1", "key": "k1", "model": "m1"}])
    monkeypatch.setenv("RELAY_KEYS_JSON", full[: len(full) // 2])
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    router, warnings, http = _build_router(make_args())
    try:
        assert any("无法解析" in w for w in warnings), f"应当给出警告，实际：{warnings}"
        assert router is None or not router.providers, "坏密钥不该产生 provider"
    finally:
        if http is not None:
            # syncio.run, not get_event_loop().run_until_complete. The latter works when
            # this file runs alone and raises RuntimeError: There is no current event loop
            # once an earlier test in the same session has closed the loop -- so the test
            # passed in isolation and failed in CI, which is the worst way to be wrong.
            import asyncio

            asyncio.run(http.aclose())


def test_the_parse_warning_survives_having_no_providers(monkeypatch) -> None:
    """The warning used to be discarded on precisely the path that needs it.

    `if not providers: return None, ["未找到任何可用的模型密钥"], None` replaced the
    accumulated list, so "a secret arrived broken" was reported as "no keys found" -- two
    problems that need completely different responses.
    """
    full = json.dumps([{"baseUrl": "https://a.example/v1", "key": "k1", "model": "m1"}])
    monkeypatch.setenv("RELAY_KEYS_JSON", full[: len(full) // 2])
    for env_name in ("GEMINI_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY",
                     "SAMBANOVA_API_KEY", "NVIDIA_API_KEY", "MISTRAL_API_KEY",
                     "HUGGINGFACE_API_KEY", "MODELSCOPE_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env_name, raising=False)

    _router, warnings, http = _build_router(make_args())
    try:
        assert any("无法解析" in w for w in warnings), "解析失败的警告必须保留"
        assert any("未找到任何可用的模型密钥" in w for w in warnings)
    finally:
        if http is not None:
            # syncio.run, not get_event_loop().run_until_complete. The latter works when
            # this file runs alone and raises RuntimeError: There is no current event loop
            # once an earlier test in the same session has closed the loop -- so the test
            # passed in isolation and failed in CI, which is the worst way to be wrong.
            import asyncio

            asyncio.run(http.aclose())


def test_a_json_object_instead_of_a_list_is_refused(monkeypatch) -> None:
    monkeypatch.setenv("RELAY_KEYS_JSON", '{"baseUrl": "https://a.example/v1"}')
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    _router, warnings, http = _build_router(make_args())
    try:
        assert any("无法解析" in w for w in warnings)
    finally:
        if http is not None:
            # syncio.run, not get_event_loop().run_until_complete. The latter works when
            # this file runs alone and raises RuntimeError: There is no current event loop
            # once an earlier test in the same session has closed the loop -- so the test
            # passed in isolation and failed in CI, which is the worst way to be wrong.
            import asyncio

            asyncio.run(http.aclose())
