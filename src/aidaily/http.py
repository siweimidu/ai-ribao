"""HTTP layer: timeouts, bounded retries, per-host politeness, conditional requests.

Three rules shape this module, each learned from the audited code:

* **Never retry a 4xx.** A 403 means the source refuses automated access; retrying it
  three times just annoys the operator and burns the run budget. Only 5xx, timeouts and
  connection errors are retried. (dailydawn's `_RETRY` makes the same call for rate
  limits: "重试只会白等配额窗口".)
* **Be polite by default.** A per-host minimum interval keeps 12 Reddit URLs from
  looking like an attack, and a UA that names the project lets an operator contact us.
* **Classify, do not just fail.** `blocked` (401/403/429) and `dead` (DNS/TLS/404) need
  different fixes, so the outcome carries the distinction forward into health records.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlsplit

import httpx

DEFAULT_UA = (
    "ai-daily/0.1 (+https://github.com/siweimidu; feed aggregator; contact via repository issues)"
)

BLOCKED_CODES = {401, 403, 429}
RETRYABLE_CODES = {500, 502, 503, 504, 522, 524}


@dataclass
class HttpResult:
    ok: bool
    url: str
    status: int | None = None
    body: bytes = b""
    content_type: str = ""
    # ok | not_modified | blocked | dead
    verdict: str = "dead"
    detail: str = ""
    attempts: int = 1

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


@dataclass
class HostLimiter:
    """Minimum spacing between requests to the same host."""

    min_interval: float = 0.5
    _last: dict[str, float] = field(default_factory=dict)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def _lock(self, host: str) -> asyncio.Lock:
        if host not in self._locks:
            self._locks[host] = asyncio.Lock()
        return self._locks[host]

    async def wait(self, url: str) -> None:
        host = urlsplit(url).hostname or ""
        async with self._lock(host):
            last = self._last.get(host)
            if last is not None:
                elapsed = time.monotonic() - last
                if elapsed < self.min_interval:
                    await asyncio.sleep(self.min_interval - elapsed)
            self._last[host] = time.monotonic()


class HttpClient:
    def __init__(
        self,
        *,
        timeout_s: float = 20.0,
        retries: int = 2,
        min_host_interval: float = 0.5,
        user_agent: str = DEFAULT_UA,
        max_bytes: int = 4_000_000,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.timeout_s = timeout_s
        self.retries = retries
        self.limiter = HostLimiter(min_host_interval)
        self.max_bytes = max_bytes
        self.headers = {"User-Agent": user_agent, "Accept": "*/*", **(headers or {})}
        # ETag/Last-Modified validators, supplied by the caller and persisted by it.
        self.validators: dict[str, dict[str, str]] = {}
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "HttpClient":
        self._client = httpx.AsyncClient(
            follow_redirects=True, timeout=self.timeout_s, headers=self.headers
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get(self, url: str, *, conditional: bool = True) -> HttpResult:
        if self._client is None:
            raise RuntimeError("HttpClient must be used as an async context manager")

        req_headers: dict[str, str] = {}
        if conditional and (v := self.validators.get(url)):
            req_headers.update(v)

        last_detail = ""
        for attempt in range(1, self.retries + 2):
            await self.limiter.wait(url)
            try:
                resp = await self._client.get(url, headers=req_headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_detail = f"{type(exc).__name__}: {exc}"[:200]
            except Exception as exc:  # noqa: BLE001 - one bad source must not kill a run
                return HttpResult(False, url, None, b"", "", "dead", f"{type(exc).__name__}: {exc}"[:200], attempt)
            else:
                if resp.status_code == 304:
                    return HttpResult(True, url, 304, b"", "", "not_modified", "304 Not Modified", attempt)

                if resp.status_code < 400:
                    if etag := resp.headers.get("ETag"):
                        self.validators.setdefault(url, {})["If-None-Match"] = etag
                    if lm := resp.headers.get("Last-Modified"):
                        self.validators.setdefault(url, {})["If-Modified-Since"] = lm
                    body = resp.content[: self.max_bytes]
                    return HttpResult(
                        True, url, resp.status_code, body,
                        resp.headers.get("Content-Type", ""), "ok", "", attempt,
                    )

                if resp.status_code in BLOCKED_CODES:
                    # 429 deserves one polite wait; 401/403 do not -- they need a
                    # different access method, not another attempt.
                    if resp.status_code == 429 and attempt <= self.retries:
                        delay = _retry_after(resp.headers.get("Retry-After"))
                        last_detail = f"HTTP 429 (waited {delay:.0f}s)"
                        await asyncio.sleep(delay)
                        continue
                    return HttpResult(
                        False, url, resp.status_code, b"", "", "blocked",
                        f"HTTP {resp.status_code} {resp.reason_phrase}", attempt,
                    )

                if resp.status_code in RETRYABLE_CODES:
                    last_detail = f"HTTP {resp.status_code} {resp.reason_phrase}"
                else:
                    return HttpResult(
                        False, url, resp.status_code, b"", "", "dead",
                        f"HTTP {resp.status_code} {resp.reason_phrase}", attempt,
                    )

            if attempt <= self.retries:
                await asyncio.sleep(min(2 ** attempt + random.random(), 30))

        return HttpResult(False, url, None, b"", "", "dead", last_detail or "exhausted retries", self.retries + 1)


def _retry_after(raw: str | None, cap: float = 30.0) -> float:
    if not raw:
        return 5.0
    try:
        return max(1.0, min(float(raw), cap))
    except ValueError:
        return 5.0
