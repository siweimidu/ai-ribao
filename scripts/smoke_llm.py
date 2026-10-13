"""One-shot end-to-end smoke test of the LLM layer against a real provider.

MockTransport proves the routing logic; it cannot prove the request shape is accepted by
a real API. This makes exactly two calls:

  1. `GET /models`  -- free, picks a cheap model without hardcoding a name that may retire
  2. one chat call with `max_tokens=16` asking for a 12-character JSON object

Total cost is a few dozen tokens. Keys are read from the path you pass and never printed.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aidaily.llm import Budget, ProviderSpec, Router  # noqa: E402

# Preference order: cheap, fast, widely available on free tiers.
MODEL_PREFERENCE = (
    "llama-3.1-8b-instant", "gpt-oss-20b", "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile", "gemini-2.5-flash-lite", "gemini-flash-lite-latest",
    "qwen3-8b", "mistral-small-latest",
)


def pick_model(ids: list[str]) -> str | None:
    for want in MODEL_PREFERENCE:
        for got in ids:
            if got == want or got.endswith("/" + want) or want in got:
                return got
    # Fall back to the shortest id: usually the smallest model.
    return sorted(ids, key=len)[0] if ids else None


async def main() -> int:
    keys_path = Path(sys.argv[1])
    provider_filter = sys.argv[2].lower() if len(sys.argv) > 2 else "groq"
    doc = json.loads(keys_path.read_text(encoding="utf-8"))

    row = None
    for r in doc.get("keys") or []:
        blob = f"{r.get('platform','')} {r.get('label','')} {r.get('baseUrl','')}".lower()
        if provider_filter in blob:
            row = r
            break
    if row is None:
        print(f"no entry matching {provider_filter!r}")
        return 1

    base = str(row.get("baseUrl") or "").rstrip("/")
    key = str(row.get("key") or "")
    print(f"provider : {row.get('label') or row.get('platform')}  ({base})")

    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
        print(f"GET /models -> {resp.status_code}")
        ids: list[str] = []
        try:
            d = resp.json()
            rows = d.get("data") if isinstance(d, dict) else d
            ids = [x.get("id") for x in rows if isinstance(x, dict) and x.get("id")]
        except Exception as exc:  # noqa: BLE001
            print(f"  could not parse model list: {exc}")

        model = pick_model(ids)
        print(f"models   : {len(ids)}  -> chosen: {model}")
        if not model:
            return 1

        spec = ProviderSpec(
            id="smoke", tier="official-free", base_url=base, model=model,
            key_literal=key, timeout_s=30,
        )
        router = Router([spec], http, budget=Budget(max_calls=2, max_tokens=5000),
                        env={}, relay_max_calls=5)
        got = await router.complete_json(
            [
                {"role": "system", "content": "You reply with JSON only."},
                {"role": "user", "content": 'Reply exactly: {"ok":true,"n":1}'},
            ],
            temperature=0.0,
            # Not 16: `openai/gpt-oss-*` are reasoning models, and a tiny cap is spent
            # entirely on reasoning tokens, yielding an empty `content`.
            max_tokens=128,
            purpose="smoke",
        )

    print(f"\nresponse : {got}")
    print(f"usage    : {router.budget.snapshot()}")
    print(f"latency  : {router.stats.events[-1].get('latency_ms')} ms")
    print(f"provider : {router.stats.used}")
    ok = isinstance(got, dict) and got.get("ok") is True
    print("\nSMOKE:", "PASS" if ok else f"unexpected shape: {got!r}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
