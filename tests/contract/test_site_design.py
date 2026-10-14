"""Design and accessibility contracts for the generated site.

These are the machine-checkable halves of the design rules. The process is "look at it and
judge", but several criteria are numbers or structural facts, and those belong in CI:

  * **type scale** — under ~4x there is no scale contrast at all
  * **section variety** — a page whose every band is "heading + paragraph" reads as a
    template even with perfect type
  * **no invented proof** — a number the user did not supply does not go on the page
  * **nothing hidden behind motion** — content must not depend on an animation having run;
    this actually shipped once, when the first stories were `opacity: 0` until an observer
    fired
  * **no slop patterns** — the trailing-dot cursor, the uniform hover lift, the violet
    gradient, monospace dressing on small labels, middle-dot metadata strings

The tests read the real rendered HTML and CSS, not a mock: the last several bugs in this
file were all "the source was right and the artifact was stale".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
ASSETS = SITE / "assets"
BUILT = ROOT / "data" / "digests" / "site"


def _strip_comments(text: str) -> str:
    """Remove CSS/JS comments before asserting on content.

    Every test here is written to catch a pattern in *code*, and the code documenting
    "do not do X" contains X. Without this the suite reports the prose explaining a rule as
    a violation of it.
    """
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"(?m)^\s*//.*$", " ", text)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    return text


@pytest.fixture(scope="module")
def tokens_code() -> str:
    return _strip_comments((ASSETS / "tokens.css").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def components_code() -> str:
    return _strip_comments((ASSETS / "components.css").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def components_raw() -> str:
    return (ASSETS / "components.css").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def motion_code() -> str:
    return _strip_comments((ASSETS / "motion.js").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def site_source() -> str:
    return (ROOT / "src" / "aidaily" / "site.py").read_text(encoding="utf-8")


def _rem(value: str) -> float:
    return float(value.replace("rem", "")) * 16


def _block(css: str, selector: str) -> str:
    idx = css.index(selector)
    return css[idx:css.index("}", idx)]


# =============================== type scale ======================================
def test_type_scale_ratio_meets_the_floor(tokens_code: str) -> None:
    """Display ÷ body must clear 4x, the measured floor for having any contrast at all.

    A three-track layout makes the content column narrow, so the display size comes down
    relative to a single-column page — but the ratio still has to hold, which is why body
    is 15px rather than the 17px a wider column would allow.
    """
    display = re.search(r"--fs-display:\s*clamp\(([\d.]+)rem,[^,]+,\s*([\d.]+)rem\)", tokens_code)
    body = re.search(r"--fs-body:\s*([\d.]+)rem", tokens_code)
    assert display and body, "type scale tokens missing"

    ratio = _rem(display.group(2)) / _rem(body.group(1))
    assert ratio >= 4.0, f"display/body = {ratio:.1f}x, below the 4x floor"
    assert ratio <= 12.0, f"display/body = {ratio:.1f}x is beyond the measured range"


def test_cjk_leading_and_tracking_are_not_latin_values(tokens_code: str, components_raw: str) -> None:
    """A display face at the same optical size reads heavier in CJK and needs *more*
    line-height; tight negative tracking closes counters fast."""
    lh = re.search(r"--lh-tight:\s*([\d.]+)", tokens_code)
    assert lh, "--lh-tight missing"
    assert float(lh.group(1)) >= 1.15, "the tight leading is too tight for CJK"

    rule = re.search(r"\.issue__title\s*\{([^}]+)\}", components_raw)
    assert rule, ".issue__title rule missing"
    ls = re.search(r"letter-spacing:\s*(-?[\d.]+)em", rule.group(1))
    if ls:
        assert float(ls.group(1)) > -0.03, f"tracking {ls.group(1)}em closes CJK counters"


def test_body_leading_is_generous_enough_for_long_form(tokens_code: str) -> None:
    lh = re.search(r"--lh-body:\s*([\d.]+)", tokens_code)
    assert lh and float(lh.group(1)) >= 1.5


def test_cjk_typeface_is_named_before_the_latin_one(tokens_code: str) -> None:
    """Latin-first stacks leave CJK to an uncontrolled system fallback: the metrics and the
    glyph shapes change per machine. Naming a CJK family first keeps them stable."""
    stack = re.search(r"--font-sans:\s*([^;]+);", tokens_code)
    assert stack, "--font-sans missing"
    first = stack.group(1).split(",")[0].strip().strip('"')
    assert any(name in first for name in ("Sarasa", "Noto Sans CJK", "PingFang", "Heiti")), (
        f"the first family is {first!r}, which does not cover CJK"
    )


# =============================== palette ========================================
def test_palette_has_no_violet_gradient(tokens_code: str) -> None:
    for banned in ("#6366f1", "#a855f7", "#8b5cf6", "#7c3aed"):
        assert banned not in tokens_code.lower(), f"{banned} is the default AI gradient"
    assert "linear-gradient" not in tokens_code, "gradients as decoration are out"


def test_dark_mode_has_both_entry_points(tokens_code: str) -> None:
    """The system preference AND the reader's explicit choice, with identical values.

    The first version only listened to `prefers-color-scheme` while the sidebar wrote
    `data-theme`, so the theme control looked functional and changed nothing.
    """
    assert "prefers-color-scheme: dark" in tokens_code
    assert ':root[data-theme="dark"]' in tokens_code
    assert ':root[data-theme="light"]' in tokens_code

    system = tokens_code.split("prefers-color-scheme: dark", 1)[1]
    system = system[:system.index("}")]
    forced = _block(tokens_code, ':root[data-theme="dark"]')

    for token in ("--bg", "--fg", "--border", "--accent"):
        a = re.search(rf"{token}:\s*(#[0-9a-fA-F]{{6}})", system)
        b = re.search(rf"{token}:\s*(#[0-9a-fA-F]{{6}})", forced)
        assert a and b, f"{token} missing from one dark-mode entry point"
        assert a.group(1).lower() == b.group(1).lower(), (
            f"{token} differs between system and manual dark mode "
            f"({a.group(1)} vs {b.group(1)}) — the toggle would look broken"
        )


def test_theme_preference_survives_a_private_mode(motion_code: str) -> None:
    """localStorage throws when storage is blocked; the read must not break the page."""
    assert "localStorage.getItem" in motion_code
    assert "localStorage.setItem" in motion_code
    assert motion_code.count("catch") >= 2, "storage access must be guarded"


# =============================== slop gates =====================================
def test_no_trailing_dot_cursor(motion_code: str) -> None:
    assert "cursor-follower" not in motion_code
    assert "trailingDot" not in motion_code


def test_no_uniform_hover_lift(components_code: str) -> None:
    """`translateY(-4px)` on every card is motion that means nothing."""
    assert "translateY(-4px)" not in components_code
    assert "translateY(-6px)" not in components_code


def test_motion_is_not_one_easing_and_one_duration(components_code: str, tokens_code: str) -> None:
    durations = set(re.findall(r"--dur-(\w+):", tokens_code))
    assert len(durations) >= 4, f"need a duration scale, found {durations}"
    assert "0.3s ease" not in components_code


def test_no_monospace_dressing_on_labels(components_code: str) -> None:
    """A monospace face used to make small labels look technical is a named tell.

    Monospace stays available for genuine code and digit columns; what is banned is dressing
    a UI label in it. An earlier version had four such labels (eyebrow, fact-label,
    evidence, source-more) and they all read as generated chrome.
    """
    offenders = [
        sel.strip()
        for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", components_code)
        if "font-mono" in body and not re.search(r"code|pre|kbd", sel, re.I)
    ]
    assert not offenders, f"monospace on non-code elements: {offenders}"


def test_no_middle_dot_metadata_strings(site_source: str) -> None:
    """`A · B · C` chrome is a template tell, and those separators carried no meaning.

    Scoped to *rendered* markup, so two things are excluded and both are corrections to the
    test rather than exemptions from the rule:

    * a middle dot inside `<title>` is the browser-tab naming convention (`Page · Site`) and
      never renders as page chrome;
    * the comment explaining this rule quotes `A · B`, and a naive scan reports the
      explanation as a violation — the same trap the CSS tests hit.
    """
    code = re.sub(r"(?m)^\s*#.*$", " ", site_source)
    code = re.sub(r'"""[\s\S]*?"""', " ", code)
    visible = "\n".join(line for line in code.splitlines() if "<title>" not in line)
    literal = re.findall(r'"([^"]*·[^"]*)"', visible)
    assert not literal, f"middle-dot metadata strings: {literal[:3]}"


# =============================== content honesty =================================
def test_content_is_never_hidden_behind_motion(components_code: str, motion_code: str) -> None:
    """The bug that actually shipped: `.enter { opacity: 0 }` in CSS meant that when the
    observer did not fire, the first stories were invisible and the page looked empty.
    Hiding must be switched on by JS, so a JS failure leaves content visible."""
    bare = re.findall(r"(?<!js-motion )\.enter\s*\{[^}]*opacity:\s*0", components_code)
    assert not bare, "`.enter` must not hide content on its own; gate it behind `.js-motion`"
    assert "js-motion" in components_code and "js-motion" in motion_code
    assert "classList.add('js-motion')" in motion_code


def test_reduced_motion_branch_keeps_the_page_intact(components_code: str) -> None:
    marker = "@media (prefers-reduced-motion: reduce)"
    assert marker in components_code
    start = components_code.index(marker) + len(marker)
    depth = 0
    end = start
    for i in range(start, len(components_code)):
        if components_code[i] == "{":
            depth += 1
        elif components_code[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    block = components_code[start:end]
    assert "display: none" not in block, "nothing may be hidden in the reduced-motion branch"
    assert "opacity: 1 !important" in block


def test_no_invented_proof(site_source: str) -> None:
    """A8: a number the user did not supply does not go on the page.

    Asserted after stripping the module docstring — it names these patterns to explain why
    they are banned, and a naive scan flags the explanation.
    """
    body = re.sub(r'"""[\s\S]*?"""', " ", site_source, count=1)
    for tell in ("50,000+", "+47%", "trusted by", "testimonial"):
        assert tell.lower() not in body.lower(), f"invented proof: {tell}"


def test_the_reset_monitor_does_not_invent_records(site_source: str) -> None:
    """The reference site shows "22 resets in 90 days". Its data source is an X account and
    every public X-to-RSS bridge is dead (RSSHub 404, Nitter 410), so those numbers cannot
    be sourced here.

    The page must render an explicit empty state instead. A fabricated reset history is
    indistinguishable from a real one on the page, which is the one thing this project
    cannot afford.
    """
    assert "还没有记录" in site_source, "the monitor must say so when it has no data"
    assert "不展示任何未经来源核实的数字" in site_source


# =============================== motion correctness ==============================
def test_spring_is_frame_rate_independent(motion_code: str) -> None:
    assert "Math.exp(-k * dt)" in motion_code
    assert "x += d * 0.1" not in motion_code


def test_integration_step_is_clamped(motion_code: str) -> None:
    """A backgrounded tab hands you a multi-second dt; an unclamped spring explodes."""
    assert "Math.min(dt, 1 / 30)" in motion_code


def test_motion_respects_reduced_motion_at_runtime(motion_code: str) -> None:
    assert "prefers-reduced-motion: reduce" in motion_code


def test_only_transform_and_opacity_are_transitioned(components_code: str) -> None:
    """Animating width/height/top forces layout on every frame."""
    transitions = re.findall(r"transition:\s*([^;]+);", components_code)
    assert transitions, "no transitions found; the regex or the CSS changed shape"
    for rule in transitions:
        for prop in ("width", "height", "top", "left", "margin", "padding"):
            assert prop not in rule, f"transition animates layout property: {rule.strip()}"


def test_every_js_file_parses() -> None:
    """A leftover TypeScript annotation killed the entire script while the Python suite
    stayed green: search, theme, calendar and the TOC all died silently.

    `node --check` is used when available; otherwise a narrow check for the exact mistake
    that shipped, since a full parse needs a JS engine.
    """
    import shutil
    import subprocess

    files = sorted(p for p in ASSETS.glob("*.js"))
    assert files, "no JavaScript assets found"

    node = shutil.which("node")
    if node:
        for path in files:
            proc = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
            assert proc.returncode == 0, f"{path.name} 语法错误: {proc.stderr.strip()[:200]}"
    else:
        for path in files:
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"\((id|el|e|dt|node): *[A-Za-z]", text), (
                f"{path.name} 含 TypeScript 类型标注，浏览器会拒绝整份文件"
            )


# =============================== structure =======================================
def test_sidebar_has_the_requested_items_in_order(site_source: str) -> None:
    """The eight items the user specified, in the order they specified."""
    order = ["搜索往期内容", "首页", "cal__grid", "Tibo 重置监控", "微信公众号",
             "订阅 RSS", "主题", "下载 markdown"]
    positions = [site_source.index(token) for token in order]
    assert positions == sorted(positions), "sidebar items are out of the requested order"


def test_calendar_marks_today_with_an_accent_circle(tokens_code: str, components_raw: str) -> None:
    """The user asked for the current day highlighted in the accent colour, kept circular,
    with a circular shadow."""
    today = re.search(r"\.cal__day\[data-today=\"true\"\]\s*\{([^}]+)\}", components_raw)
    assert today, "no rule for today's date"
    body = today.group(1)
    assert "var(--accent)" in body, "today must use the accent colour"
    assert "box-shadow" in body, "today must keep a circular halo"

    base = re.search(r"\.cal__day\s*\{([^}]+)\}", components_raw)
    assert base and "border-radius: 50%" in base.group(1), "calendar days must be circular"


def test_page_has_a_right_hand_table_of_contents(site_source: str) -> None:
    assert "toc__nav" in site_source
    assert 'aria-label="目录"' in site_source


def test_page_has_at_least_three_different_section_shapes(site_source: str) -> None:
    """A3: the same internal structure in every band reads as a template."""
    for shape in ("rail", "cal", "toc", "section__title", "stats"):
        assert shape in site_source, f"missing structural shape: {shape}"


def test_hero_is_not_the_default_centred_block(components_raw: str) -> None:
    """A1: full-bleed, centred H1, centred subhead, two buttons."""
    rule = re.search(r"\.issue__head\s*\{([^}]+)\}", components_raw)
    assert rule and "text-align: center" not in rule.group(1)


def test_layout_is_three_tracks_not_a_centred_column(tokens_code: str) -> None:
    """The reference site's defining structure: a sticky rail, the content, and a TOC rail."""
    assert "var(--rail-w) minmax(0, 1fr)" in tokens_code
    assert "var(--toc-w)" in tokens_code
    assert "position: sticky" in tokens_code


def test_sections_come_from_both_shapes_of_the_data(site_source: str, tokens_code: str) -> None:
    """`sections` is `{category: [Event]}` in memory but `{category: [event_id]}` in the
    archived JSON. Reading only the first shape put all 60 stories into "其它" on the real
    page, which is how it was found."""
    assert 'isinstance(row, str)' in site_source
    assert 'getattr(row, "event_id"' in site_source


def test_the_multi_source_label_exists() -> None:
    """`mixed` had no entry in the label table, so the most corroborated stories in the
    issue — the ones the clustering stage exists to find — were labelled "其它" and sorted
    last."""
    from aidaily.render import CATEGORY_LABELS

    assert "mixed" in CATEGORY_LABELS
    assert CATEGORY_LABELS["mixed"] == "多源验证"


def test_story_links_come_from_captured_urls(site_source: str) -> None:
    """Every link in the digest must be one we recorded — never a model-supplied link."""
    assert "event.all_urls" in site_source
    assert "insight.url" not in site_source and "insight['url']" not in site_source


# =============================== build integrity =================================
def test_committed_assets_match_their_source() -> None:
    """`site/assets` is the source; the built copy is what gets deployed, so they can drift.

    They did: editing the source and re-rendering with the flag that skips delivery meant
    auditing and screenshotting a build that no longer existed, twice.
    """
    assert BUILT.exists(), "产物目录不存在；跑一次完整分发"
    for src in sorted(ASSETS.iterdir()):
        if not src.is_file():
            continue
        built = BUILT / "assets" / src.name
        assert built.exists(), f"{src.name} 未拷贝到产物目录"
        assert built.read_bytes() == src.read_bytes(), (
            f"{src.name} 与产物不一致；用 --no-llm 重渲染（--no-deliver 不拷贝资源）"
        )


def test_every_linked_path_is_actually_deployed() -> None:
    """A page that links a URL the deploy never uploads is a 404 with extra steps.

    This shipped twice: the feeds were written outside `site/`, and then the markdown
    download links pointed at filenames the writer did not produce.
    """
    assert BUILT.exists(), "产物目录不存在"
    linked: set[str] = set()
    for page in BUILT.glob("*.html"):
        for href in re.findall(r'href="([^"#:]+)"', page.read_text(encoding="utf-8")):
            if href.startswith(("http", "data:", "mailto:", "//")):
                continue
            linked.add(href.split("?", 1)[0])
    assert linked, "页面里没有相对链接；生成器或正则变了形状"
    missing = sorted(h for h in linked if not (BUILT / h).exists())
    assert not missing, f"页面链接了未部署的路径：{missing}"
