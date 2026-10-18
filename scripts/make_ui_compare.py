"""Build one HTML file showing three UI variants on the real page, switchable.

The screenshots did not reach the user, so the comparison has to be a file they can open. This
inlines the site's own stylesheets (relative URLs rewritten to the deployed origin so nothing
404s) and puts all three variants behind a switcher, so a click changes the design without
changing the content -- the same 60 headlines in every variant.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "data" / "digests" / "site"
OUT = ROOT / "data" / "state" / "ui-compare"
ORIGIN = "https://siweimidu.github.io/ai-ribao/"
DATE = "2026-10-17"

FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    'family=Noto+Serif+SC:wght@400;600;700;900'
    '&family=IBM+Plex+Mono:wght@400;500&display=swap">'
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans@4.0.0/lib/Normal/MiSans-Regular.min.css">'
)

A = """
html[data-ui="a"] body { background: #fbfaf7; }
html[data-ui="a"] .content { max-width: 46rem; }
html[data-ui="a"] .issue__head { border-top: 3px double var(--fg); padding-top: 1.5rem; }
html[data-ui="a"] .issue__date { letter-spacing: .18em; text-transform: uppercase; font-size: .72rem; }
html[data-ui="a"] .issue__title { font-weight: 800; letter-spacing: -.035em; line-height: 1.05; }
html[data-ui="a"] .stats { border-top: 1px solid var(--border); border-bottom: 1px solid var(--border);
  padding-block: 1.1rem; margin-block: 2rem; }
html[data-ui="a"] .stats b { font-size: 1.1rem; font-weight: 600; }
html[data-ui="a"] .stats span { letter-spacing: .1em; text-transform: uppercase; font-size: .68rem; }
html[data-ui="a"] .section { margin-top: 3.25rem; }
html[data-ui="a"] .section__title { font-family: var(--f-serif); font-size: 1.6rem;
  letter-spacing: -.02em; border-bottom: 1px solid var(--border); padding-bottom: .5rem; }
html[data-ui="a"] .section__count { font-size: .7rem; letter-spacing: .12em; text-transform: uppercase; }
html[data-ui="a"] .item { padding: 1.15rem 0; border-bottom: 1px solid var(--border); }
html[data-ui="a"] .item__title { font-family: var(--f-serif); font-weight: 700; line-height: 1.35; }
html[data-ui="a"] .item__no { font-family: var(--f-mono); font-size: .8rem; color: var(--accent);
  padding-top: .22rem; }
"""

B = """
html[data-ui="b"] body { background: #f6f7f9; }
html[data-ui="b"] .issue__head { padding-bottom: 1.5rem; }
html[data-ui="b"] .stats { background: #fff; border: 1px solid var(--border); border-radius: 1rem;
  padding: 1.25rem 1.5rem; margin-block: 1.85rem; box-shadow: 0 1px 2px rgba(16,24,40,.04); }
html[data-ui="b"] .section { margin-top: 2.5rem; }
html[data-ui="b"] .section__title { font-size: 1.05rem; font-weight: 650; letter-spacing: 0; }
html[data-ui="b"] .item { background: #fff; border: 1px solid var(--border); border-radius: .9rem;
  padding: 1.15rem 1.35rem; margin-bottom: .7rem; box-shadow: 0 1px 2px rgba(16,24,40,.04);
  transition: box-shadow .18s, transform .18s; }
html[data-ui="b"] .item:hover { box-shadow: 0 6px 20px rgba(16,24,40,.09); transform: translateY(-1px); }
html[data-ui="b"] .item__title { font-weight: 650; line-height: 1.4; }
html[data-ui="b"] .item__no { width: 1.35rem; height: 1.35rem; border-radius: 50%;
  background: var(--accent-soft); color: var(--accent); display: grid; place-items: center;
  font-family: var(--f-mono); font-size: .68rem; font-weight: 600; flex: none; }
"""

C = """
html[data-ui="c"] body { background: #fdfcf9; }
html[data-ui="c"] .content { max-width: 52rem; }
html[data-ui="c"] .issue__title { font-weight: 800; letter-spacing: -.04em; line-height: 1.02;
  border-bottom: 2px solid var(--fg); padding-bottom: .4rem; }
html[data-ui="c"] .stats { gap: 0; margin-block: 1.25rem; padding-block: .8rem;
  border-top: 1px solid var(--fg); border-bottom: 1px solid var(--fg); }
html[data-ui="c"] .stats div { border-right: 1px solid var(--border); padding-right: 1.1rem; }
html[data-ui="c"] .stats div:last-child { border-right: 0; }
html[data-ui="c"] .stats b { font-size: .95rem; }
html[data-ui="c"] .section { margin-top: 2.15rem; }
html[data-ui="c"] .section__title { font-family: var(--f-sans); font-size: .78rem; font-weight: 700;
  letter-spacing: .16em; text-transform: uppercase; border-bottom: 1px solid var(--fg);
  padding-bottom: .35rem; }
html[data-ui="c"] .item { padding: .62rem 0; border-bottom: 1px dotted var(--border); }
html[data-ui="c"] .item__title { font-size: .96rem; line-height: 1.45; }
html[data-ui="c"] .item__meta { display: none; }
html[data-ui="c"] .item__no { font-family: var(--f-mono); font-size: .72rem; color: var(--muted-fg); }
"""

BAR = """
<div id="uibar">
  <b>UI 方案</b>
  <button data-ui="a">A · 编辑部</button>
  <button data-ui="b">B · 卡片</button>
  <button data-ui="c">C · 报纸</button>
  <span class="hint">点按钮切换，内容是同一份 2026-10-17</span>
</div>
<script>
(function(){
  var root = document.documentElement;
  var btns = document.querySelectorAll("#uibar button");
  function apply(v){
    root.setAttribute("data-ui", v);
    btns.forEach(function(b){ b.setAttribute("aria-pressed", b.dataset.ui === v ? "true" : "false"); });
  }
  btns.forEach(function(b){ b.addEventListener("click", function(){ apply(b.dataset.ui); }); });
  apply("a");
})();
</script>
"""

BAR_CSS = """
#uibar { position: fixed; left: 0; right: 0; bottom: 0; z-index: 2147483647; background: #16181c;
  color: #fff; padding: 12px 20px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
  font: 500 14px/1.4 system-ui, sans-serif; box-shadow: 0 -2px 16px rgba(0,0,0,.3); }
#uibar b { font-weight: 600; opacity: .6; margin-right: 6px; letter-spacing: .04em; }
#uibar button { background: #2a2a2e; color: #eee; border: 1px solid #3a3a40; border-radius: 999px;
  padding: 7px 18px; font: inherit; cursor: pointer; transition: .15s; }
#uibar button:hover { background: #3a3a42; }
#uibar button[aria-pressed="true"] { background: #0065fd; border-color: #0065fd; color: #fff; }
#uibar .hint { opacity: .5; margin-left: auto; font-size: 13px; }
body { padding-bottom: 64px; }
"""


def inlined_css() -> str:
    """The site's own stylesheets, with relative URLs pointed at the deployed origin.

    Rewriting to absolute URLs is what an earlier attempt got wrong: it made paths relative to a
    *copy* that had no sibling files, so the layout collapsed and the comparison was worthless.
    """
    parts = []
    for name in ("tokens.css", "components.css"):
        path = SITE / "assets" / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        # Rewrite only the relative asset references. Done by scanning for "url(" and taking the
        # text up to the closing paren, rather than one clever regex: the quote handling in the
        # single-line version produced a pattern Python could not even parse.
        out = []
        i = 0
        while True:
            j = text.find("url(", i)
            if j < 0:
                out.append(text[i:])
                break
            out.append(text[i:j])
            k = text.find(")", j)
            if k < 0:
                out.append(text[j:])
                break
            ref = text[j + 4:k].strip().strip(chr(34)).strip(chr(39))
            if ref.startswith(("http", "data:")):
                out.append(text[j:k + 1])
            else:
                out.append('url("' + ORIGIN + "assets/" + ref.lstrip("./") + '")')
            i = k + 1
        parts.append("/* ---- " + name + " ---- */\n" + "".join(out))
    return "\n".join(parts)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    html = (SITE / (DATE + ".html")).read_text(encoding="utf-8")
    html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)
    html = re.sub(
        r'(src|href)="(?!#|https?:|data:|mailto:)([^"]*)"',
        lambda m: m.group(1) + '="' + ORIGIN + m.group(2) + '"',
        html,
    )
    style = "<style>" + inlined_css() + "\n" + A + B + C + BAR_CSS + "</style>"
    html = html.replace("</head>", FONTS + style + "</head>", 1)
    html = re.sub(r"</body>", BAR + "</body>", html, count=1)

    path = OUT / "UI三版对照.html"
    path.write_text(html, encoding="utf-8")
    print("  " + str(path) + "  (" + str(path.stat().st_size // 1024) + " KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
