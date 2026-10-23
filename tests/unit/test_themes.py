"""Themes are whole palettes, and Claude light is the default.

A theme is not a hue rotation: a dark palette needs a different contrast ratio and a different
accent lightness to stay readable, so each one is written out in `tokens.css` rather than
generated from one seed. This test keeps them complete and in sync with the picker.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOKENS = (ROOT / "site" / "assets" / "tokens.css").read_text(encoding="utf-8")
SITE = (ROOT / "src" / "aidaily" / "site.py").read_text(encoding="utf-8")
MOTION = (ROOT / "site" / "assets" / "motion.js").read_text(encoding="utf-8")

#: Every variable a theme must define. A missing one falls back to the `:root` default, which
#: on a dark palette produces dark text on a dark background.
REQUIRED = (
    "--bg", "--surface", "--fg", "--muted-fg",
    "--muted", "--border", "--accent", "--accent-soft",
)


def _themes() -> dict[str, str]:
    """name -> the block that defines it."""
    out: dict[str, str] = {}
    for match in re.finditer(r'\:root\[data-theme="([^"]+)"\]\s*\{([^}]*)\}', TOKENS):
        out[match.group(1)] = match.group(2)
    return out


def test_claude_light_is_the_default() -> None:
    assert "DEFAULT_THEME = 'claude-light'" in MOTION


def test_every_theme_defines_every_variable() -> None:
    for name, block in _themes().items():
        for var in REQUIRED:
            assert f"{var}:" in block, f"{name} is missing {var}"


def test_the_picker_offers_every_theme_that_exists() -> None:
    """A palette nobody can select is dead code; a button with no palette is a broken one."""
    defined = set(_themes())
    offered = set(re.findall(r'\("([a-z-]+)", "[^"]+"\)', SITE))
    offered = {name for name in offered if name in defined or name in {"light", "dark"}}
    missing_buttons = defined - offered
    assert not missing_buttons, f"defined but not offered: {sorted(missing_buttons)}"


def test_every_offered_theme_has_a_label() -> None:
    """The rail summary shows the name; an unmapped key falls back to 自动."""
    for name in _themes():
        assert f"{name}:" in MOTION or f"'{name}':" in MOTION, f"no label for {name}"


def test_the_shipped_set_is_exactly_four() -> None:
    """The palette list is the user's to decide. Five candidates were added, reviewed, and
    removed; this pins the set that survived so a stray block cannot linger unnoticed.
    """
    assert set(_themes()) == {"dark", "light", "claude-light", "claude-dark"}


def test_a_dark_theme_has_light_text() -> None:
    """Sanity check on the one failure that is invisible in a screenshot of the rail."""
    for name in ("midnight", "forest", "claude-dark", "dark"):
        block = _themes().get(name, "")
        bg = re.search(r"--bg:\s*#([0-9a-f]{6})", block)
        fg = re.search(r"--fg:\s*#([0-9a-f]{6})", block)
        if not (bg and fg):
            continue
        bg_lum = sum(int(bg.group(1)[i:i + 2], 16) for i in (0, 2, 4)) / 3
        fg_lum = sum(int(fg.group(1)[i:i + 2], 16) for i in (0, 2, 4)) / 3
        assert fg_lum > bg_lum + 80, f"{name}: text and background are too close"