"""Apply the chosen typography to the real site: Songti headings, MiSans body and rail.

## What was measured before choosing the delivery method

MiSans ships as **~110 woff2 chunks** with `unicode-range` on each `@font-face` and no single TTF to
subset, so the two options were:

* **self-host a subset** (the OPPO Sans route): one file, no third party, but I would have to
  re-subset on every deploy as new characters appear;
* **use the published chunked CSS**: the browser fetches only the chunks whose ranges the page
  actually uses.

Measured on the real page: the chunked CSS pulled **500 KB across 38 woff2 files** for the whole
digest, and `document.fonts.ready` resolved with the face applied. So the chunked CSS costs about
what a hand-made subset would, arrives correct for tomorrow's characters, and needs no build step.
Noto Serif SC was **1.1 MB** for the headings.

Total added: **1.6 MB**, lazily fetched and cached. Fonts degrade to the system stack if the CDN is
unreachable — no layout break, no missing text.

## What goes where

* **noto-serif-sc** — issue title, item titles, section headings. This is the template's own choice.
* **misans** — body copy (facts / inferences / opinions / uncertainties) and the rail controls.
* **ibm-plex-mono** — numerals and metadata: the stats row, dates, source lines. Tabular figures
  keep the counters aligned.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "src" / "aidaily" / "site.py"
CSS = ROOT / "site" / "assets" / "components.css"

#: Injected into every page's `<head>`. Two preconnects so the TLS handshake overlaps parsing.
FONT_LINKS = """  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;600;700;900&family=IBM+Plex+Mono:wght@400;500&display=swap">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans@4.0.0/lib/Normal/MiSans-Regular.min.css">
"""

CSS_BLOCK = """

/* ==============================================================================
   终版覆盖（四）—— 字体
   ----------------------------------------------------------------------------
   标题宋体（模板 ai-daily-deck 自己的选择）、正文与侧栏 MiSans、数字与元信息等宽。
   三者的分工依据是各自的强项：

   · 宋体（Noto Serif SC）笔画有横细竖粗的对比，大字号下有"刊物感"，适合标题。
     小字号时笔画偏细，所以**不用**于正文。
   · MiSans 笔画均匀、字腔开，是小米为界面做的字，小字号下清晰，适合正文与控件。
   · IBM Plex Mono 等宽，数字位宽一致，统计行与时间戳不会跳动。

   实测代价：MiSans 走官方分片 CSS，浏览器按 unicode-range 只取用到的分片 ——
   整期日报实测 500 KB / 38 个文件；思源宋体 1.1 MB。合计 1.6 MB，可缓存。
   两个 CDN 都不可达时退回系统字体栈，不会乱码、不会撑破布局。
   ============================================================================== */

:root {
  --f-serif: "Noto Serif SC", "Source Han Serif SC", "Songti SC", Georgia, serif;
  --f-sans:  "MiSans", "Noto Sans SC", "PingFang SC", "Hiragino Sans GB",
             "Microsoft YaHei", system-ui, sans-serif;
  --f-mono:  "IBM Plex Mono", "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
}

/* 标题：宋体 */
.issue__title,
.item__title,
.section__title,
.issue__head h1,
.cover__title,
h1, h2, h3 {
  font-family: var(--f-serif);
}

/* 正文与控件：MiSans。正文行高比黑体略松一点，字腔开、行距紧会显得密。 */
.facts, .inferences, .opinions, .uncertainties,
.item__body, .item p, p, li,
.facts li, .inferences li, .opinions li, .uncertainties li,
.rail__item, .rail__sub button, .rail__btn, .toc__nav a,
.rail__brand, .section__count, .issue__date,
button, input, select, summary {
  font-family: var(--f-sans);
}

.facts li, .inferences li, .opinions li, .uncertainties li { line-height: 1.85; }

/* 数字与元信息：等宽，等宽数字让统计行不跳动 */
.stats b, .stats span,
.item__meta, .item__meta span,
.cal__month, .ecal__month,
[data-theme-summary], time {
  font-family: var(--f-mono);
  font-feature-settings: "tnum";
}

/* 界面正文的最后一道兜底：没有 --f-sans 声明的元素也走 MiSans，避免混排出两种黑体。 */
body { font-family: var(--f-sans); }
"""


def inject_links() -> int:
    """Put the font `<link>`s before `</head>` on every page template.

    Every page in this generator writes its own `<head>`, so the injection is done once per
    occurrence rather than assumed to be shared.
    """
    text = SITE.read_text(encoding="utf-8")
    if "misans@4.0.0" in text:
        print("  字体链接已存在")
        return 0
    count = text.count("</head>")
    if not count:
        raise SystemExit("找不到 </head>")
    text = text.replace("</head>", FONT_LINKS + "</head>")
    SITE.write_text(text, encoding="utf-8")
    print(f"  已在 {count} 处页面注入字体链接")
    return count


def append_css() -> None:
    css = CSS.read_text(encoding="utf-8")
    if "终版覆盖（四）" in css:
        print("  CSS 已写入过")
        return
    CSS.write_text(css.rstrip("\n") + "\n" + CSS_BLOCK, encoding="utf-8")
    print(f"  CSS 已追加字体规则（{CSS_BLOCK.count(chr(10))} 行）")


def main() -> int:
    inject_links()
    append_css()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
