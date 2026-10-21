"""The GitHub repository card: one component, two outputs.

## Why HTML *and* an image

The page shows HTML. Text stays selectable, searchable, translatable, theme-aware, and a card
costs about 1 KB instead of 60 KB. But two consumers cannot use HTML:

* **RSS.** A feed item is read in a feed reader that may render no CSS at all, and the aggregator
  that feeds n8n wants an image URL it can attach. `<enclosure>` needs a bitmap.
* **Download / share.** A screenshot of a card is what gets pasted into a chat.

So the same data renders twice: `card_html()` for the page and feed body, `card_png()` for the
enclosure and the download link. They share every string, so they cannot drift.

## Why the layout is themed

The page ships four themes. A fixed palette would look pasted in on three of them, so the HTML
card reads only `var(--...)` tokens. The PNG has no CSS context, so it takes an explicit theme
argument and resolves those same tokens to concrete colours.
"""

from __future__ import annotations

import html as H

#: Colour GitHub itself uses for a language, so a reader who knows the ecosystem recognises the
#: swatch in the bar.
LANG_COLOURS = {
    "Python": "#3572A5", "Rust": "#dea584", "Cuda": "#3A4E3A", "C++": "#f34b7d",
    "C": "#555555", "Shell": "#89e051", "CMake": "#DA3434", "TypeScript": "#3178c6",
    "JavaScript": "#f1e05a", "Go": "#00ADD8", "Java": "#b07219", "Jupyter Notebook": "#DA5B0B",
    "Dockerfile": "#384d54", "Makefile": "#427819", "HTML": "#e34c26", "CSS": "#563d7c",
}

#: The four site themes, resolved to concrete colours for the PNG renderer. These mirror
#: `site/assets/tokens.css`; a test asserts they stay in step.
THEMES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#fdfcfa", "surface": "#ffffff", "fg": "#16181c",
        "muted": "#6b7280", "border": "#e6e4df", "accent": "#0065fd",
        "serif": 'Georgia, "Songti SC", serif',
    },
    "dark": {
        "bg": "#101215", "surface": "#171a1f", "fg": "#e9ecef",
        "muted": "#9aa4b2", "border": "#282d36", "accent": "#6ba1ff",
        "serif": 'Georgia, "Songti SC", serif',
    },
    "claude-light": {
        "bg": "#faf9f5", "surface": "#ffffff", "fg": "#1f1e1d",
        "muted": "#6b6862", "border": "#e5e2d9", "accent": "#c15f3c",
        "serif": 'Georgia, "Songti SC", serif',
    },
    "claude-dark": {
        "bg": "#262624", "surface": "#30302e", "fg": "#f0eee6",
        "muted": "#a8a49b", "border": "#3f3e3a", "accent": "#d97757",
        "serif": 'Georgia, "Songti SC", serif',
    },
}

STYLE = """
.ghm{
  font-family:var(--font-sans); color:var(--fg); background:var(--surface);
  border:1px solid var(--border); border-radius:var(--radius);
  padding:calc(var(--unit) * 7) calc(var(--unit) * 7);
  text-decoration:none; display:block;
  transition:border-color var(--dur-fast) ease, box-shadow var(--dur-fast) ease;
}
.ghm:hover{
  border-color:color-mix(in srgb, var(--accent) 40%, var(--border));
  box-shadow:0 10px 30px -20px color-mix(in srgb, var(--fg) 40%, transparent);
}
.ghm__kicker{font-size:var(--fs-micro); letter-spacing:.18em; text-transform:uppercase;
  color:var(--accent); font-weight:640}
.ghm__title{font-family:Georgia,"Songti SC","Noto Serif CJK SC",serif;
  font-size:clamp(1.9rem,3.4vw,2.6rem); line-height:1.08; letter-spacing:-.022em;
  font-weight:700; margin:calc(var(--unit) * 3) 0 0}
.ghm__owner{color:var(--muted-fg); font-weight:400}
.ghm__desc{font-family:Georgia,"Songti SC",serif; font-size:1.0625rem; line-height:1.62;
  color:color-mix(in srgb, var(--fg) 78%, var(--muted-fg)); margin:calc(var(--unit) * 4) 0 0; max-width:62ch}
.ghm__rule{height:1px; background:var(--border); margin:calc(var(--unit) * 7) 0 0}
.ghm__stats{display:flex; flex-wrap:nowrap; overflow-x:auto; margin-top:calc(var(--unit) * 5);
  gap:0; scrollbar-width:none}
.ghm__stats::-webkit-scrollbar{display:none}
.ghm__stat{padding-right:calc(var(--unit) * 5); margin-right:calc(var(--unit) * 5);
  border-right:1px solid var(--border); flex:0 1 auto}
.ghm__stat:last-child{border-right:0; margin-right:0; padding-right:0}
.ghm__stat b{display:block; font-family:Georgia,"Songti SC",serif;
  font-size:clamp(1.25rem, 2.2vw, 1.6rem);
  line-height:1; letter-spacing:-.03em; font-variant-numeric:tabular-nums}
.ghm__stat i{display:block; font-style:normal; margin-top:calc(var(--unit) * 2);
  font-size:var(--fs-micro); letter-spacing:.1em; text-transform:uppercase; color:var(--muted-fg)}
.ghm__langs{margin-top:calc(var(--unit) * 7)}
.ghm__bar{display:flex; height:8px; border-radius:4px; overflow:hidden; background:var(--muted)}
.ghm__bar span{display:block; height:100%}
.ghm__legend{display:flex; flex-wrap:wrap; gap:calc(var(--unit) * 5);
  margin-top:calc(var(--unit) * 3); font-size:var(--fs-micro); color:var(--muted-fg)}
.ghm__legend em{display:inline-block; width:8px; height:8px; border-radius:50%;
  margin-right:5px; vertical-align:baseline; font-style:normal}
"""


def _k(n: int) -> str:
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def _shown_languages(languages: dict[str, float] | None) -> list[tuple[str, float]]:
    """Languages worth drawing, renormalised so the bar fills its row exactly.

    Dropping a language that rounds to 0% is right -- a legend entry reading "Shell 0%" is noise.
    But the remaining segments must then be rescaled, or a project whose tail was dropped shows a
    bar that stops at 85% and looks broken.
    """
    if not languages:
        return []
    shown = [(name, pct) for name, pct in languages.items() if round(pct) >= 1]
    total = sum(pct for _, pct in shown) or 1.0
    return [(name, 100.0 * pct / total) for name, pct in shown]


def _stats(*, stars: int, forks: int, contributors: int | None, discussions: int | None) -> list[tuple[str, str]]:
    out = [(_k(stars), "Stars"), (_k(forks), "Forks")]
    if contributors:
        out.append((_k(contributors), "Contributors"))
    if discussions:
        out.append((_k(discussions), "Discussions"))
    return out


def card_html(
    *,
    full_name: str,
    description: str,
    stars: int,
    forks: int,
    contributors: int | None = None,
    discussions: int | None = None,
    languages: dict[str, float] | None = None,
    license_: str = "",
    href: str | None = None,
) -> str:
    """The card as HTML, themed by whichever `[data-theme]` is active on the page."""
    owner, _, name = full_name.partition("/")
    # `NOASSERTION` is what GitHub reports when it cannot identify the licence. Printing it
    # reads as "this project has no licence", which is a claim about the project rather than
    # about GitHub parser. Omit it and say nothing.
    shown_license = "" if license_.upper() in ("", "NOASSERTION", "NONE") else license_
    kicker = "Open source" + (f" · {shown_license}" if shown_license else "")

    stats_html = "".join(
        f'<div class="ghm__stat"><b>{v}</b><i>{label}</i></div>'
        for v, label in _stats(
            stars=stars, forks=forks, contributors=contributors, discussions=discussions
        )
    )

    langs_html = ""
    shown = _shown_languages(languages)
    if shown:
        segs = "".join(
            f'<span style="width:{pct:.2f}%;background:{LANG_COLOURS.get(lang, "#8b949e")}"></span>'
            for lang, pct in shown
        )
        legend = "".join(
            f'<span><em style="background:{LANG_COLOURS.get(lang, "#8b949e")}"></em>'
            f"{H.escape(lang)} {round(pct)}%</span>"
            for lang, pct in shown
        )
        langs_html = (
            f'<div class="ghm__langs"><div class="ghm__bar">{segs}</div>'
            f'<div class="ghm__legend">{legend}</div></div>'
        )

    return (
        f'<a class="ghm" href="{H.escape(href or "https://github.com/" + full_name)}" '
        'target="_blank" rel="noopener noreferrer">'
        f'<div class="ghm__kicker">{H.escape(kicker)}</div>'
        f'<div class="ghm__title">{H.escape(name)}'
        f'<span class="ghm__owner"> / {H.escape(owner)}</span></div>'
        f'<p class="ghm__desc">{H.escape(description)}</p>'
        '<div class="ghm__rule"></div>'
        f'<div class="ghm__stats">{stats_html}</div>'
        f"{langs_html}"
        '</a>'
    )


def _png_document(theme: str, **kwargs) -> str:
    """A standalone HTML document for one card, with the theme resolved to concrete colours."""
    palette = THEMES.get(theme, THEMES["light"])
    owner, _, name = str(kwargs["full_name"]).partition("/")
    shown_license = "" if str(kwargs.get("license_") or "").upper() in ("", "NOASSERTION", "NONE") else kwargs["license_"]
    kicker = "Open source" + (f" · {shown_license}" if shown_license else "")
    stats = _stats(
        stars=kwargs["stars"], forks=kwargs["forks"],
        contributors=kwargs.get("contributors"), discussions=kwargs.get("discussions"),
    )
    shown = _shown_languages(kwargs.get("languages"))

    stats_html = "".join(
        f'<div class="s"><b>{v}</b><i>{label}</i></div>' for v, label in stats
    )
    langs_html = ""
    if shown:
        segs = "".join(
            f'<span style="width:{pct:.2f}%;background:{LANG_COLOURS.get(lang, "#8b949e")}"></span>'
            for lang, pct in shown
        )
        legend = "".join(
            f'<span><em style="background:{LANG_COLOURS.get(lang, "#8b949e")}"></em>'
            f"{H.escape(lang)} {round(pct)}%</span>"
            for lang, pct in shown
        )
        langs_html = f'<div class="bar">{segs}</div><div class="legend">{legend}</div>'

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;background:{palette["bg"]}}}
body{{padding:40px;font-family:Georgia,"Songti SC",serif}}
.card{{background:{palette["surface"]};border:1px solid {palette["border"]};
  border-radius:16px;padding:44px 48px}}
.kicker{{font:640 13px/1 -apple-system,"Segoe UI",sans-serif;letter-spacing:.18em;
  text-transform:uppercase;color:{palette["accent"]}}}
.title{{font:700 44px/1.08 Georgia,serif;letter-spacing:-.022em;color:{palette["fg"]};margin-top:14px}}
.title span{{color:{palette["muted"]};font-weight:400}}
.desc{{font:400 19px/1.6 Georgia,serif;color:{palette["fg"]};opacity:.82;margin-top:18px;max-width:60ch}}
.rule{{height:1px;background:{palette["border"]};margin:30px 0 0}}
.stats{{display:flex;margin-top:22px}}
.s{{padding-right:44px;margin-right:44px;border-right:1px solid {palette["border"]}}}
.s:last-child{{border:0;margin:0;padding:0}}
.s b{{display:block;font:700 30px/1 Georgia,serif;letter-spacing:-.03em;color:{palette["fg"]}}}
.s i{{display:block;font:400 11px/1 -apple-system,sans-serif;font-style:normal;
  letter-spacing:.1em;text-transform:uppercase;color:{palette["muted"]};margin-top:8px}}
.bar{{display:flex;height:8px;border-radius:4px;overflow:hidden;margin-top:28px;
  background:{palette["border"]}}}
.bar span{{display:block;height:100%}}
.legend{{display:flex;gap:20px;margin-top:12px;font:400 12px/1 -apple-system,sans-serif;
  color:{palette["muted"]}}}
.legend em{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px;
  vertical-align:baseline;font-style:normal}}
</style></head><body><div class="card">
<div class="kicker">{H.escape(kicker)}</div>
<div class="title">{H.escape(name)}<span> / {H.escape(owner)}</span></div>
<p class="desc">{H.escape(kwargs["description"])}</p>
<div class="rule"></div>
<div class="stats">{stats_html}</div>
{langs_html}
</div></body></html>"""


async def card_png(theme: str = "light", **kwargs) -> bytes | None:
    """Render one card to PNG. Returns None when Playwright is unavailable.

    Used for the RSS `<enclosure>` and the download link. The page itself uses `card_html`, so
    this only runs for the few stories that need a bitmap -- rendering every card twice would
    cost more time than the picture is worth.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    document = _png_document(theme, **kwargs)
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(
                viewport={"width": 1080, "height": 400}, device_scale_factor=2
            )
            await page.set_content(document, wait_until="load")
            node = page.locator(".card")
            data = await node.screenshot(type="png")
            await browser.close()
            return data
    except Exception:
        return None
