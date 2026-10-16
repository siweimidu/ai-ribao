"""One self-contained file with a switcher for all four body faces.

Four separate screenshots are hard to compare -- the eye cannot hold two texts side by side across
files. This puts the **real page** in one file with a button per candidate, so the same paragraph
can be switched between faces without moving.

The page's CSS is inlined (relative asset links are rewritten to the deployed origin so nothing
404s), and each candidate loads only the font it needs. Every face is behind the same heading
treatment -- Songti -- so the only thing a click changes is the body and rail.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "data" / "digests" / "site"
OUT = ROOT / "data" / "state" / "font-compare"
DATE = "2026-10-16"
ORIGIN = "https://siweimidu.github.io/ai-ribao/"

FONTS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;500;600;700;900&family=Noto+Sans+SC:wght@300;400;500;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/lxgw-wenkai-webfont@1.7.0/style.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans@4.0.0/lib/Normal/MiSans-Regular.min.css">
"""

#: Body + rail face per candidate. `data-face` selects which rule applies.
SWITCHER_CSS = """
:root{
  --f-serif:"Noto Serif SC","Source Han Serif SC","Songti SC",Georgia,serif;
  --f-wenkai:"LXGW WenKai","LXGW WenKai Screen",Georgia,serif;
  --f-misans:"MiSans","Noto Sans SC","PingFang SC",system-ui,sans-serif;
  --f-sans:"Noto Sans SC","PingFang SC","Hiragino Sans GB","Microsoft YaHei",system-ui,sans-serif;
  --f-mono:"IBM Plex Mono","JetBrains Mono","SFMono-Regular",Consolas,monospace;
}
/* 标题一律宋体 —— 这是模板自己的做法，四个方案都相同 */
.issue__title,.item__title,.section__title,h1,h2,h3,.issue__head h1,.rail__brand{font-family:var(--f-serif);}
.stats b,.cal__month,.ecal__month,[data-theme-summary],.item__meta,.stats span,
.item__meta,.section__count,.issue__date{font-family:var(--f-mono);font-feature-settings:"tnum";}

/* 正文与侧栏：由 data-face 决定 */
.facts,.inferences,.opinions,.uncertainties,.item__body,.item p,p,li,.issue__lead,
.facts li,.inferences li,.opinions li,.uncertainties li,
.rail__item,.rail__sub button,.rail__btn,.toc__nav a,button,input,select,summary{
  font-family:var(--f-sans);
}
html[data-face="wenkai"] .facts,html[data-face="wenkai"] .inferences,
html[data-face="wenkai"] .opinions,html[data-face="wenkai"] .uncertainties,
html[data-face="wenkai"] .item p,html[data-face="wenkai"] p,html[data-face="wenkai"] li,
html[data-face="wenkai"] .issue__lead,
html[data-face="wenkai"] .rail__item,html[data-face="wenkai"] .rail__sub button,
html[data-face="wenkai"] .rail__btn,html[data-face="wenkai"] .toc__nav a,
html[data-face="wenkai"] button,html[data-face="wenkai"] summary{font-family:var(--f-wenkai);}

html[data-face="misans"] .facts,html[data-face="misans"] .inferences,
html[data-face="misans"] .opinions,html[data-face="misans"] .uncertainties,
html[data-face="misans"] .item p,html[data-face="misans"] p,html[data-face="misans"] li,
html[data-face="misans"] .issue__lead,
html[data-face="misans"] .rail__item,html[data-face="misans"] .rail__sub button,
html[data-face="misans"] .rail__btn,html[data-face="misans"] .toc__nav a,
html[data-face="misans"] button,html[data-face="misans"] summary{font-family:var(--f-misans);}

html[data-face="serif"] .facts,html[data-face="serif"] .inferences,
html[data-face="serif"] .opinions,html[data-face="serif"] .uncertainties,
html[data-face="serif"] .item p,html[data-face="serif"] p,html[data-face="serif"] li,
html[data-face="serif"] .issue__lead,
html[data-face="serif"] .rail__item,html[data-face="serif"] .rail__sub button,
html[data-face="serif"] .rail__btn,html[data-face="serif"] .toc__nav a,
html[data-face="serif"] button,html[data-face="serif"] summary{font-family:var(--f-serif);}

/* 楷体与宋体的行高要比黑体松一点，否则密 */
html[data-face="wenkai"] .facts li,html[data-face="wenkai"] .inferences li,
html[data-face="wenkai"] .opinions li,html[data-face="wenkai"] .uncertainties li,
html[data-face="serif"] .facts li,html[data-face="serif"] .inferences li,
html[data-face="serif"] .opinions li,html[data-face="serif"] .uncertainties li{line-height:1.85;}

/* 切换条 */
#fontbar{position:fixed;left:0;right:0;bottom:0;z-index:2147483647;background:#111;
  color:#fff;padding:12px 20px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;
  font:500 14px/1.4 system-ui,sans-serif;box-shadow:0 -2px 16px rgba(0,0,0,.28)}
#fontbar b{font-weight:600;margin-right:6px;opacity:.75}
#fontbar button{background:#2a2a2e;color:#eee;border:1px solid #3a3a40;border-radius:999px;
  padding:7px 16px;font:inherit;cursor:pointer;transition:.15s}
#fontbar button:hover{background:#3a3a42}
#fontbar button[aria-pressed="true"]{background:#0065fd;border-color:#0065fd;color:#fff}
#fontbar .hint{opacity:.55;margin-left:auto;font-size:13px}
body{padding-bottom:64px}
"""

BAR = """
<div id="fontbar">
  <b>正文字体：</b>
  <button data-face="sans">A · 无衬线（现在）</button>
  <button data-face="wenkai">B · 霞鹜文楷</button>
  <button data-face="misans">C · MiSans</button>
  <button data-face="serif">D · 思源宋体</button>
  <span class="hint">标题始终是宋体；点按钮只换正文与侧栏</span>
</div>
<script>
(function(){
  var root=document.documentElement, btns=document.querySelectorAll('#fontbar button');
  function apply(f){
    root.setAttribute('data-face', f);
    btns.forEach(function(b){ b.setAttribute('aria-pressed', b.dataset.face===f ? 'true':'false'); });
  }
  btns.forEach(function(b){ b.addEventListener('click', function(){ apply(b.dataset.face); }); });
  apply('sans');
})();
</script>
"""


def css_for_inline() -> str:
    """The site's own stylesheets, with relative URLs pointed at the deployed origin.

    Rewriting to absolute URLs is what the earlier attempt got wrong: it made paths *relative to a
    copy* that had no siblings. Absolute URLs cannot miss.
    """
    out = []
    for name in ("tokens.css", "components.css"):
        p = SITE / "assets" / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        text = re.sub(r'url\((["\']?)(?!https?:|data:)([^)"\']+)\1\)',
                      lambda m: f'url("{ORIGIN}assets/{m.group(2).lstrip("./")}")', text)
        out.append(f"/* {name} */\n{text}")
    return "\n".join(out)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    html = (SITE / f"{DATE}.html").read_text(encoding="utf-8")
    html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)
    # Keep navigation working by pointing it at the live site rather than at nothing.
    html = re.sub(r'href="(?!#|https?:|data:)([^"]*)"', lambda m: f'href="{ORIGIN}{m.group(1)}"', html)
    html = re.sub(r'<script[^>]*></script>', "", html)
    html = html.replace("</head>", FONTS + f"<style>{css_for_inline()}\n{SWITCHER_CSS}</style></head>", 1)
    html = re.sub(r"</body>", BAR + "</body>", html, count=1)

    path = OUT / "字体对照-可切换.html"
    path.write_text(html, encoding="utf-8")
    print(f"  {path}  ({path.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
