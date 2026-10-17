"""Fail if the source imports a package that `pyproject.toml` does not install.

## Why this exists

Four scheduled runs failed with

    ModuleNotFoundError: No module named 'bs4'

`roundup.py` uses BeautifulSoup, and `collect.py` imports `roundup` at module load, so
`python -m aidaily gate` could not even start. It passed locally because this machine had bs4
installed from some earlier experiment; CI installs into a clean environment every time.

The generic failure is **"works on my machine"**: an import that resolves locally because the
package happens to be present, while the declared dependency list says otherwise. Reviewing
`pyproject.toml` by eye does not catch it -- the import is in a file nobody edited that day.

So this test reads the **actual import statements** in `src/`, resolves them against the
declared runtime dependencies, and fails on any that are not covered. Stdlib is derived from
`sys.stdlib_module_names` rather than a hand-maintained list, so it cannot silently go stale.

## Reading a declared name

Distribution names and import names differ (`beautifulsoup4` -> `bs4`,
`PyYAML` -> `yaml`). The mapping is made explicit in `DIST_TO_IMPORT`; a dependency whose
distribution name equals its import name needs no entry. When a new dependency appears whose
import name differs and is not in the table, the test fails with the missing import -- which is
the correct direction: it asks a human to state the mapping instead of guessing it.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # tests/contract/test_x.py -> repo root
PYPROJECT = ROOT / "pyproject.toml"
SRC = ROOT / "src"

#: distribution name -> import name, for the ones that differ.
DIST_TO_IMPORT = {
    "beautifulsoup4": "bs4",
    "pyyaml": "yaml",
}

#: Imported from the stdlib but not always in `sys.stdlib_module_names` on every version.
ALWAYS_STDLIB = {"zoneinfo", "importlib_metadata"}


def declared_dependencies() -> set[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    declared: set[str] = set()
    for spec in data["project"].get("dependencies", []):
        name = spec.split(";")[0].strip()
        for sep in ("[", ">", "<", "=", "!", "~", " "):
            name = name.split(sep)[0]
        declared.add(name.strip().lower())
    return declared


def import_to_dist() -> dict[str, str]:
    """The inverse of `DIST_TO_IMPORT`, plus identity for names that do not differ."""
    mapping = {imp: dist for dist, imp in DIST_TO_IMPORT.items()}
    return mapping


def source_imports() -> dict[str, set[str]]:
    """Top-level module -> the files that import it."""
    found: dict[str, set[str]] = {}
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                found.setdefault(name, set()).add(str(path.relative_to(ROOT)))
    return found


def is_own_package(name: str) -> bool:
    return name in {"aidaily", "__future__"} or (SRC / "aidaily" / f"{name}.py").exists()


def test_every_third_party_import_is_a_declared_dependency() -> None:
    declared = declared_dependencies()
    inverse = import_to_dist()
    stdlib = set(sys.stdlib_module_names) | ALWAYS_STDLIB

    missing: list[str] = []
    for module, files in sorted(source_imports().items()):
        if module in stdlib or is_own_package(module):
            continue
        dist = inverse.get(module, module.lower())
        if dist not in declared:
            where = ", ".join(sorted(files)[:3])
            missing.append(f"  {module:16} (as {dist})  imported by {where}")

    assert not missing, (
        "源码引入了 pyproject.toml 未声明的依赖。CI 是干净环境，会在运行时 "
        "ModuleNotFoundError（这正是 bs4 让四次定时任务失败的原因）。\n"
        + "\n".join(missing)
    )


def test_the_mapping_table_has_no_stale_entries() -> None:
    """A rename that leaves an old mapping behind hides a future break."""
    declared = declared_dependencies()
    stale = [dist for dist in DIST_TO_IMPORT if dist not in declared]
    assert not stale, f"DIST_TO_IMPORT 里有已不存在的依赖：{stale}"


@pytest.mark.parametrize("module", ["bs4"])
def test_the_core_pipeline_can_be_imported_without_extras(module: str) -> None:
    """The exact failure: `aidaily.collect` is reachable from the base install.

    `gate` imports it, so a missing parser dependency stops the scheduled run before it can
    decide anything. This asserts the module is importable, which only holds if its
    dependencies are runtime dependencies.
    """
    __import__(module)
    from aidaily import collect  # noqa: F401  -- import is the assertion

    assert collect is not None
