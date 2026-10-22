"""A coroutine must not call `asyncio.run`.

Measured on 2026-10-22: `deliver_all` is itself a coroutine. Inside it, the pages branch called
`asyncio.run(fetch_many(...))` to fetch repository metadata. Python raises

    RuntimeError: asyncio.run() cannot be called from a running event loop

and a bare `except Exception: repo_meta = {}` swallowed it. The consequence: the GitHub cards
were rendered to PNG, uploaded and reported in the log -- and the page rendered none of them,
because `render_item` received an empty metadata map.

The check here is static: an `asyncio.run` inside an `async def` is always wrong, whatever it
wraps. A test that ran the function would need a live API; the shape of the code is what fails.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "aidaily"


def _nested_asyncio_run(path: Path) -> list[tuple[int, str]]:
    """Every `asyncio.run(...)` that sits inside an async function."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef,)):
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "run"
                and isinstance(func.value, ast.Name)
                and func.value.id == "asyncio"
            ):
                offenders.append((child.lineno, node.name))
    return offenders


def test_no_coroutine_calls_asyncio_run() -> None:
    """`asyncio.run` inside `async def` raises at runtime; nothing has to be executing to see it."""
    problems: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        for lineno, func in _nested_asyncio_run(path):
            problems.append(f"{path.name}:{lineno} inside async def {func}()")
    assert not problems, "asyncio.run() cannot be called from a running loop:\n  " + "\n  ".join(problems)


def test_the_scan_would_catch_a_regression() -> None:
    """Guard against the guard: a known-bad snippet must be detected."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fh:
        fh.write("import asyncio\n\nasync def f():\n    asyncio.run(g())\n")
        tmp = Path(fh.name)
    try:
        found = _nested_asyncio_run(tmp)
        assert found and found[0][1] == "f"
    finally:
        tmp.unlink(missing_ok=True)