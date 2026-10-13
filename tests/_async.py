"""A tiny async-test helper, so the suite needs no pytest-asyncio plugin.

One less dev dependency, and the failure mode is obvious: the test is a sync function
that drives its own event loop.
"""

from __future__ import annotations

import asyncio
import functools


def async_test(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    return wrapper
