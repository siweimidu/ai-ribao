"""Design and accessibility contracts for the generated site.

These are the machine-checkable halves of the motion-web skill's gates. The skill's
process is "screenshot with motion off and judge the still frame" — a human judgement —
but several of its criteria are numbers, and numbers belong in CI:

  * **type scale** — the measured median across award winners is ~8x, and under ~4x a page
    has no scale contrast at all (`page-design.md` §2)
  * **section variety** — every band being "headline + paragraph" reads as a template even
    with perfect type (`design-slop.md` A3)
  * **no invented proof** — a number the user did not supply does not go on the page (A8)
  * **nothing hidden behind motion** — content must not depend on an animation having run
    (B8); this is the failure that actually shipped once, when the first three rows were
    `opacity: 0` until an observer fired
  * **no slop patterns** — the trailing-dot cursor (B7), uniform hover lift (B1), the
    violet gradient (A4)

The tests read the real rendered HTML and CSS, not a mock, because the last three bugs in
this file were all "the source was right and the artifact was stale".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
ASSETS = SITE / "assets"


@pytest.fixture(scope="module")
def tokens_css() -> str:
    return (ASSETS / "tokens.css").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def components_css() -> str:
    return (ASSETS / "components.css").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def motion_js() -> str:
    return (ASSETS / "motion.js").read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    """Remove CSS and JS comments before asserting on content.

    Every one of these tests was written to catch a *pattern in code*, and the code that
    documents "do not do X" contains X. Without this the suite reports the prose that
    explains a rule as a violation of it.
    """
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"(?m)^\s*//.*$", " ", text)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    return text


@pytest.fixture(scope="module")
def tokens_code(tokens_css: str) -> str:
    return _strip_comments(tokens_css)


@pytest.fixture(scope="module")
def components_code(components_css: str) -> str:
    return _strip_comments(components_css)


@pytest.fixture(scope="module")
def motion_code(motion_js: str) -> str:
    return _strip_comments(motion_js)


def _rem(value: str) -> float:
    return float(value.replace("rem", "")) * 16


# =============================== type scale ======================================
def test_type_scale_ratio_meets_the_floor(tokens_css: str) -> None:
    """Display ÷ body must clear 4x, the measured floor for having any contrast.

    The first attempt was 3.8x because the display size was reduced to fix an oversized
    heading; the fix was to bring body down as well, not to shrink only one end.
    """
    display = re.search(r"--fs-display:\s*clamp\(([\d.]+)rem,[^,]+,\s*([\d.]+)rem\)", tokens_css)
    body = re.search(r"--fs-body:\s*([\d.]+)rem", tokens_css)
    assert display and body, "type scale tokens missing"

    largest = _rem(display.group(2))
    smallest = _rem(body.group(1))
    ratio = largest / smallest
    assert ratio >= 4.0, f"display/body = {ratio:.1f}x, below the 4x floor"
    assert ratio <= 12.0, f"display/body = {ratio:.1f}x is beyond the measured range"


def test_mobile_gets_its_own_scale_not_a_shrunk_one(tokens_css: str) -> None:
    """`page-design.md` §7: mobile is a different design, not a smaller one.

    The clamp's vw term collapses on a 390px viewport, so the scale has to be restated
    rather than inherited. The value is set by "the first story must be visible in the
    fold", not by hitting a ratio — a 52px heading was 4.3x but pushed all content off
    the screen.
    """
    assert "@media (max-width: 560px)" in tokens_css
    block = tokens_css.split("@media (max-width: 560px)", 1)[1]
    assert "--fs-display" in block, "mobile must restate the display size"
    assert "max-width: 100%" in block, "the desktop measure must be released on mobile"


def test_cjk_line_height_is_not_the_latin_value(tokens_css: str) -> None:
    """A display face at the same optical size reads heavier in CJK and needs *more*
    line-height; negative tracking closes counters fast (`page-design.md` §4).

    The rule appears twice — once for desktop, once inside the mobile media query — so the
    assertion is over *all* declarations rather than the first match.
    """
    declarations = re.findall(r"\.masthead h1\s*\{([^}]+)\}", tokens_css)
    assert declarations, "masthead h1 rule missing"

    for block in declarations:
        lh = re.search(r"line-height:\s*([\d.]+)", block)
        ls = re.search(r"letter-spacing:\s*(-?[\d.]+)em", block)
        if lh:
            value = float(lh.group(1))
            assert value >= 1.2, f"CJK display line-height {value} is too tight"
        if ls:
            value = float(ls.group(1))
            assert value > -0.03, f"tracking {value}em is a Latin value; CJK counters close"


def test_display_has_its_own_sizes_not_everything_mid_range(tokens_css: str) -> None:
    """Everything between 16 and 48px is the band a default build lands in."""
    display = re.search(r"--fs-display:\s*clamp\([^,]+,[^,]+,\s*([\d.]+)rem\)", tokens_css)
    assert _rem(display.group(1)) >= 48, "the display size must leave the mid range"


# =============================== palette ========================================
def test_palette_is_small_and_has_no_violet_gradient(tokens_css: str) -> None:
    """`design-slop.md` A4: the violet/indigo gradient is the most reliable AI tell."""
    for banned in ("#6366f1", "#a855f7", "#8b5cf6", "#7c3aed"):
        assert banned not in tokens_css.lower(), f"{banned} is the default AI gradient"
    assert "linear-gradient" not in tokens_css, "gradients as a background treatment are out"

    accent = re.findall(r"--accent:\s*(#[0-9a-f]{6})", tokens_css.lower())
    assert len(set(accent)) <= 2, f"accent should be one hue (plus its dark-mode variant), got {accent}"


def test_dark_mode_comes_from_the_system_not_a_fake_toggle(components_css: str, tokens_css: str) -> None:
    assert "prefers-color-scheme: dark" in tokens_css
    assert "theme-toggle" not in components_css
    assert "localStorage" not in (ASSETS / "motion.js").read_text(encoding="utf-8")


# =============================== slop gates =====================================
def test_no_trailing_dot_cursor(motion_js: str) -> None:
    """B7: a circle lerping behind the pointer was a 2019 signature, now a default."""
    assert "cursor-follower" not in motion_js
    assert "trailingDot" not in motion_js


def test_no_uniform_hover_lift(components_css: str) -> None:
    """B1: `translateY(-4px)` on every card is motion that means nothing."""
    assert "translateY(-4px)" not in components_css
    assert "translateY(-6px)" not in components_css


def test_motion_is_not_one_easing_and_one_duration(components_code: str, tokens_css: str) -> None:
    """B3: a single `0.3s ease` across the page is a CSS default."""
    durations = set(re.findall(r"--dur-(\w+):", tokens_css))
    assert len(durations) >= 4, f"need a duration scale, found {durations}"
    assert "0.3s ease" not in components_code


def test_entrance_is_limited_to_a_few_things(components_code: str) -> None:
    """B2: universal scroll fade-up teaches the reader to ignore entrances."""
    # `.enter` is applied by the generator to the masthead, the first three rows and the
    # tally — a rule that hides everything would defeat the point.
    assert components_code.count(".js-motion .enter") <= 3


# =============================== content honesty =================================
def test_content_is_never_hidden_behind_motion(components_code: str, motion_code: str) -> None:
    """B8, and the bug that actually shipped.

    The first version put `.enter { opacity: 0 }` in CSS. When the observer did not fire,
    the first three rows were invisible — the digest looked empty. Hiding must be switched
    on by JS, so a JS failure leaves content visible rather than absent.
    """
    bare = re.findall(r"(?<!js-motion )\.enter\s*\{[^}]*opacity:\s*0", components_code)
    assert not bare, "`.enter` must not hide content on its own; gate it behind `.js-motion`"
    assert "js-motion" in components_code and "js-motion" in motion_code
    assert "classList.add('js-motion')" in motion_code


def test_reduced_motion_branch_keeps_the_page_intact(components_code: str) -> None:
    """B8 again: the reduced-motion version must be the same page, not a broken one.

    Parsed by brace matching rather than `split(...)[1]`: the naive split ran on past the
    end of the media query and swallowed the `@media print` block, whose
    `display: none` on the filter chips is correct and unrelated.
    """
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


def test_no_invented_proof_in_the_generator() -> None:
    """A8: a number the user did not supply does not go on the page.

    Asserted against the module docstring *stripped* — the docstring names these very
    patterns to explain why they are banned, and a naive scan flags the explanation.
    """
    source = (ROOT / "src" / "aidaily" / "site.py").read_text(encoding="utf-8")
    body = re.sub(r'"""[\s\S]*?"""', " ", source, count=1)
    for tell in ("50,000+", "+47%", "trusted by", "trustedBy", "testimonial"):
        assert tell.lower() not in body.lower(), f"invented proof: {tell}"


# =============================== motion correctness ==============================
def test_spring_is_frame_rate_independent(motion_code: str) -> None:
    """`handfeel.md` §7.1: per-frame constant lerp is a different filter at each rate."""
    assert "Math.exp(-k * dt)" in motion_code
    assert "x += d * 0.1" not in motion_code


def test_spring_uses_underdamping_not_plain_lerp(motion_code: str) -> None:
    """§1: a plain lerp decelerates monotonically and reads as 'sliding'."""
    assert "velocity" in motion_code and "damping" in motion_code
    assert re.search(r"this\.velocity \*= this\.damping", motion_code)


def test_integration_step_is_clamped(motion_code: str) -> None:
    """Returning to a backgrounded tab hands you a multi-second dt; an unclamped spring
    explodes."""
    assert "Math.min(dt, 1 / 30)" in motion_code


def test_motion_respects_reduced_motion_at_runtime(motion_code: str) -> None:
    """The media query is checked in JS too: an OS setting changed mid-session must stop
    the springs, not just stop new transitions."""
    assert "prefers-reduced-motion: reduce" in motion_code
    assert "reduceMQ.addEventListener" in motion_code


def test_only_transform_and_opacity_are_animated(components_code: str) -> None:
    """`motion-tokens.md` transform budget: animating width/height/top forces layout."""
    transitions = re.findall(r"transition:\s*([^;]+);", components_code)
    assert transitions, "no transitions found; the regex or the CSS changed shape"
    for rule in transitions:
        for prop in ("width", "height", "top", "left", "margin", "padding"):
            assert prop not in rule, f"transition animates layout property: {rule.strip()}"


# =============================== structure =======================================
def test_page_has_at_least_three_different_section_shapes() -> None:
    """A3: the same internal structure in every band reads as a template."""
    source = (ROOT / "src" / "aidaily" / "site.py").read_text(encoding="utf-8")
    for shape in ("masthead", "stream", "archive"):
        assert shape in source, f"missing section shape: {shape}"


def test_hero_is_not_the_default_centred_block(tokens_code: str) -> None:
    """A1: full-bleed, centred H1, centred subhead, two buttons."""
    # The masthead rule lives in tokens.css; an earlier version of this test looked in
    # components.css and silently matched nothing.
    masthead = tokens_code.split(".masthead {", 1)[1].split("}", 1)[0]
    assert "text-align: center" not in masthead
    assert "grid-template-columns" in tokens_code, "the masthead should be a two-part grid"
    assert "1fr) auto" in tokens_code, "title and tally should sit side by side"


def test_story_links_are_present_and_come_from_captured_urls() -> None:
    """Every link in the digest must be one we recorded — the site renders `all_urls`,
    never a model-supplied link."""
    source = (ROOT / "src" / "aidaily" / "site.py").read_text(encoding="utf-8")
    assert "event.all_urls" in source
    assert "insight.url" not in source and "insight['url']" not in source


# =============================== build freshness =================================
def test_committed_assets_match_their_source() -> None:
    """`site/assets/` is the source; `data/digests/site/assets/` is the built copy.

    Both must exist — the deploy step uploads the built directory as a self-contained
    artifact, so it cannot reference the source path — which means they can drift. They
    did: an edit to the source followed by a `--no-deliver` re-render silently measured
    and screenshotted the old build, twice.

    Drift is a real failure of the artifact, not a test artefact, so it fails here.
    """
    source_dir = ASSETS
    built_dir = ROOT / "data" / "digests" / "site" / "assets"
    assert built_dir.exists(), "产物目录不存在；跑一次完整分发"

    for src in sorted(source_dir.iterdir()):
        if not src.is_file():
            continue
        built = built_dir / src.name
        assert built.exists(), f"{src.name} 未拷贝到产物目录"
        assert built.read_bytes() == src.read_bytes(), (
            f"{src.name} 与产物不一致；用 --no-llm 重渲染（--no-deliver 不会拷贝资源）"
        )


def test_every_linked_path_is_actually_deployed() -> None:
    """A page that links a URL the deploy never uploads is a 404 with extra steps.

    This shipped: the RSS and JSON feeds were written to `data/digests/feed/` while Pages
    uploads `data/digests/site/`, so both feeds were built correctly, linked from every
    page, and served 404. The feed is the n8n hand-off — an unpublished feed is no feed.
    """
    site_dir = ROOT / "data" / "digests" / "site"
    assert site_dir.exists(), "产物目录不存在"

    # Collect relative hrefs from the generated pages.
    linked: set[str] = set()
    for page in list(site_dir.glob("*.html")):
        text = page.read_text(encoding="utf-8")
        for href in re.findall(r'href="([^"#:]+)"', text):
            if href.startswith(("http", "data:", "mailto:", "//")):
                continue
            linked.add(href.split("?", 1)[0])

    assert linked, "页面里没有相对链接；生成器或正则变了形状"
    missing = sorted(h for h in linked if not (site_dir / h).exists())
    assert not missing, f"页面链接了未部署的路径：{missing}"


def test_feeds_are_written_into_the_published_directory() -> None:
    """Guards the fix above at the source level too, so a future edit to either writer
    that moves the output back out of `site/` fails here rather than on the live site."""
    main_src = (ROOT / "src" / "aidaily" / "__main__.py").read_text(encoding="utf-8")
    publish_src = (ROOT / "src" / "aidaily" / "publish.py").read_text(encoding="utf-8")

    assert '"site" / "feed"' in main_src, "JSON Feed must be written under site/"
    assert 'out_dir / "site" / "feed" / "zh.xml"' in publish_src, "RSS must be written under site/"
    assert 'out_dir / "feed"' not in publish_src
