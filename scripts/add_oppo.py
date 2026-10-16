"""Add OPPO Sans to the switcher, self-hosted from the subset.

## Why self-hosted

The published package is a single **22.7 MB** TTF. Subset to the characters this site renders it is
**0.51 MB** (2.3%), and it sits beside the comparison file so the page needs no CDN for it — which
also makes the comparison work offline and behind the GFW.

## OnePlus Sans

It is not available as a web font: `@fontpkg/oneplus-sans*` is 404 on npm and the mirror, there is
no `@fontsource` package, and the vendor CDN answers 403. Rather than fake it with a lookalike and
call it by the wrong name, the switcher labels it honestly: OnePlus Sans is a sibling of OPPO Sans
(both come out of the same group's type work), and the OPPO entry is the closest thing that
actually loads.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SWITCHER = ROOT / "data" / "state" / "font-compare" / "字体对照-可切换.html"

FACE_CSS = """
/* OPPO Sans —— 自托管子集（0.51 MB，只含站点用到的字） */
@font-face{
  font-family:"OPPO Sans";
  src:url("oppo-sans-subset.woff2") format("woff2");
  font-weight:400; font-style:normal; font-display:swap;
}
:root{ --f-oppo:"OPPO Sans","MiSans","Noto Sans SC",system-ui,sans-serif; }

html[data-face="oppo"] .facts,html[data-face="oppo"] .inferences,
html[data-face="oppo"] .opinions,html[data-face="oppo"] .uncertainties,
html[data-face="oppo"] .item p,html[data-face="oppo"] p,html[data-face="oppo"] li,
html[data-face="oppo"] .issue__lead,
html[data-face="oppo"] .rail__item,html[data-face="oppo"] .rail__sub button,
html[data-face="oppo"] .rail__btn,html[data-face="oppo"] .toc__nav a,
html[data-face="oppo"] button,html[data-face="oppo"] summary{font-family:var(--f-oppo);}
"""

BUTTON = '<button data-face="oppo">E · OPPO Sans</button>'

HINT_OLD = '<span class="hint">标题始终是宋体；点按钮只换正文与侧栏</span>'
HINT_NEW = (
    '<span class="hint">标题始终是宋体；点按钮只换正文与侧栏 · '
    'OnePlus Sans 无网页字体包（npm/镜像 404、官方 CDN 403），'
    '其同源兄弟 OPPO Sans 见 E</span>'
)


def main() -> int:
    html = SWITCHER.read_text(encoding="utf-8")
    if 'data-face="oppo"' in html:
        print("  已存在，跳过")
        return 0

    # The face rules go after the existing ones so they win on equal specificity.
    html = re.sub(r"(</style>)", FACE_CSS + r"\1", html, count=1)
    html = html.replace('<button data-face="serif">D · 思源宋体</button>',
                        '<button data-face="serif">D · 思源宋体</button>\n  ' + BUTTON, 1)
    html = html.replace(HINT_OLD, HINT_NEW, 1)
    SWITCHER.write_text(html, encoding="utf-8")
    print("  已加入 OPPO Sans（自托管子集）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
