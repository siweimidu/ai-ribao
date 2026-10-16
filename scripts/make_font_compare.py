"""Two self-contained font variants of the real issue page.

## Why the first attempt was useless

It copied the HTML and rewrote relative asset paths (`assets/` -> `../site/assets/`). Two things
went wrong: the rewrite missed some references, and the page links to `index.html`, `tibo.html`,
`feed/*` and its own markdown, none of which exist beside the copy. The layout collapsed, so there
was nothing to compare -- which is exactly what the user reported.

## What this does instead

**Inlines everything.** The CSS is read from the built site and embedded in `<style>`, the fonts
come from a `<link>` that works from a local file, and every internal link is stripped (they are not
the subject of the comparison). The result opens straight from disk with the real design intact, so
the only visible difference between A and B is the font.

Assets are embedded as data URIs where the CSS references them, so no sibling files are needed.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "data" / "digests" / "site"
OUT = ROOT / "data" / "state" / "font-compare"
DATE = "2026-10-16"

FONT_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '<link href="https://fonts.googleapis.com/css2?'
    "family=Playfair+Display:ital,wght@0,500;0,600;0,700;0,800;0,900;1,700"
    "&family=Noto+Serif+SC:wght@400;500;600;700;900"
    "&family=Noto+Sans+SC:wght@300;400;500;700"
    "&family=IBM+Plex+Mono:wght@300;400;500&display=swap\" rel=\"stylesheet\">"
)

VARS = """
:root{
  --f-serif:"Noto Serif SC","Source Han Serif SC","Songti SC",Georgia,serif;
  --f-display:"Playfair Display","Noto Serif SC",Georgia,serif;
  --f-sans:"Noto Sans SC","PingFang SC","Hiragino Sans GB","Microsoft YaHei",system-ui,sans-serif;
  --f-mono:"IBM Plex Mono","JetBrains Mono","SFMono-Regular",Consolas,monospace;
}
/* 标题：宋体（两个方案都一样，模板就是这么做的） */
.issue__title,.item__title,.section__title,h1,h2,h3,.rail__brand,.issue__head h1{font-family:var(--f-serif);}
/* 界面控件保持无衬线：240px 侧栏里小字号宋体难扫读 */
.rail__item,.rail__sub button,.rail__btn,.toc__nav a,button,input,select,summary,
.rail__brand,.section__count,.issue__date{font-family:var(--f-sans);}
/* 数字与元信息：等宽 */
.stats b,.cal__month,.ecal__month,[data-theme-summary],.item__meta,.stats span{font-family:var(--f-mono);}
"""

BODY_SANS = """
.facts,.inferences,.opinions,.uncertainties,.item__body,.item p,p,li,.issue__lead,.headline,
.facts li,.inferences li,.opinions li,.uncertainties li{font-family:var(--f-sans);}
"""

BODY_SERIF = """
.facts,.inferences,.opinions,.uncertainties,.item__body,.item p,p,li,.issue__lead,.headline,
.facts li,.inferences li,.opinions li,.uncertainties li{font-family:var(--f-serif);}
"""

BANNER = (
    '<div style="position:sticky;top:0;z-index:2147483647;background:#0065fd;color:#fff;'
    "font:600 15px/1.75 system-ui,sans-serif;padding:10px 22px;letter-spacing:.02em;"
    'box-shadow:0 2px 12px rgba(0,0,0,.2)">{label}</div>'
)


def inline_css() -> str:
    """Every stylesheet the page uses, concatenated, with local images as data URIs."""
    css_dir = SITE / "assets"
    parts: list[str] = []
    for name in ("tokens.css", "components.css"):
        path = css_dir / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")

        def embed(match: re.Match[str]) -> str:
            rel = match.group(1)
            target = css_dir / rel.split("?")[0].lstrip("./")
            if not target.exists():
                return match.group(0)
            mime = "image/svg+xml" if target.suffix == ".svg" else "font/woff2"
            data = base64.b64encode(target.read_bytes()).decode()
            return f'url("data:{mime};base64,{data}")'

        text = re.sub(r'url\("?([^")]+\.(?:svg|woff2|png))"?\)', embed, text)
        parts.append(f"/* ---- {name} ---- */\n{text}")
    return "\n".join(parts)


def build(name: str, extra: str, label: str) -> Path:
    html = (SITE / f"{DATE}.html").read_text(encoding="utf-8")

    # Drop the page's own stylesheet links; their contents are inlined below.
    html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)
    # Every internal link would 404 beside this file, and none of them are the subject. Make them
    # inert rather than misleading.
    html = re.sub(r'href="(?!#|https?:|data:)[^"]*"', 'href="#"', html)
    html = re.sub(r'src="(?!#|https?:|data:)[^"]*"', 'src=""', html)
    html = re.sub(r"<script[^>]*></script>", "", html)

    style = f"<style>\n{inline_css()}\n{VARS}{extra}\n</style>"
    html = html.replace("</head>", FONT_LINK + style + "</head>", 1)
    html = re.sub(r"(<body[^>]*>)", r"\1" + BANNER.format(label=label), html, count=1)

    path = OUT / name
    path.write_text(html, encoding="utf-8")
    return path


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    a = build("A-template.html", BODY_SANS,
              "方案 A · 模板的做法 —— 标题宋体 / 正文无衬线 / 数字等宽")
    b = build("B-all-serif.html", BODY_SERIF,
              "方案 B · 全部宋体 —— 标题与正文都用 Noto Serif SC")
    print(f"  A: {a}  ({a.stat().st_size // 1024} KB)")
    print(f"  B: {b}  ({b.stat().st_size // 1024} KB)")
    print("  两个文件都已内联样式，可直接双击打开")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
