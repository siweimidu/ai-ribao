"""A 304 must not be a lost payload.

The client stores validators (`ETag` / `Last-Modified`) but not response bodies, so
`304 Not Modified` says the content on the server has not changed since a copy we no longer hold.
Returning an empty body meant the source contributed nothing at all.

Measured 2026-10-24: eight sources answered 304, including `rss:daily-juya-uk` which had carried
14 stories the day before. That issue held 36 entries where the previous day held 96, and the
collection report counted those eight as successes (`sources_ok` includes `not_modified`).
"""

from __future__ import annotations

import inspect

from aidaily import http as http_module


def _code_only(source: str) -> str:
    body = source
    if '"""' in body:
        head, _, rest = body.partition('"""')
        _, _, tail = rest.partition('"""')
        body = head + tail
    return "\n".join(line.split("#")[0] for line in body.splitlines())


def test_a_304_drops_the_validator_and_retries() -> None:
    """The only way to obtain a body this client never kept."""
    code = _code_only(inspect.getsource(http_module.HttpClient.get))
    assert "validators.pop(url, None)" in code, "the stale validator must be discarded"
    assert "continue" in code, "the request must be repeated"


def test_a_repeated_304_still_returns_rather_than_looping() -> None:
    """An unconditional retry bounds it; without that guard a 304 would spin forever."""
    code = _code_only(inspect.getsource(http_module.HttpClient.get))
    assert "attempt > self.retries" in code


def test_an_unconditional_request_never_reaches_the_retry() -> None:
    """Without `conditional`, no validators were sent, so a 304 cannot be ours."""
    code = _code_only(inspect.getsource(http_module.HttpClient.get))
    assert "not conditional" in code