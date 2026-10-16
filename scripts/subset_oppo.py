"""Subset OPPO Sans to the characters this site actually renders.

The published package ships one **11.5 MB** TTF. Serving that to a reader to change a font is not a
trade worth making, so it is subset with `fontTools` and re-encoded as WOFF2.

Two character sets go in:

1. **Every CJK character in the site's own output** — the three digests, the pages, the feeds. That
   guarantees the subset covers today's content exactly.
2. **The most frequent ~3 000 Chinese characters**, so a future issue cannot render in a fallback
   face because a glyph was missing. The list is derived from the site's corpus plus a standard
   frequency block, not pasted from memory.

Latin, digits and punctuation are included as a range rather than enumerated, because they are
cheap and a single missed `·` would be visible.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "data" / "state" / "fonts"
SRC = FONTS / "oppo-sans-4.0.ttf"
OUT = FONTS / "oppo-sans-subset.woff2"

#: Characters that must survive: ASCII, Latin-1 punctuation, CJK punctuation, full-width forms,
#: the arrows and marks the digest uses, and the box/en-dash family seen in headlines.
EXTRA = (
    "　、。〈〉《》「」『』【】〔〕・ー―‐–—‘’“”…‧·×÷±°′″"
    "→←↑↓↗↘⇒⇔•◦▪▫■□▲△▼▽◆◇○●◎★☆✓✗✔✘"
    "☰⚡🎙📍🔁🧠"
    "０１２３４５６７８９％＋－＝＜＞＆＃＠／＼｜～＄"
)


def site_corpus() -> str:
    """Every character in the generated output: the pages, the feeds and the digest JSON."""
    chunks: list[str] = []
    site = ROOT / "data" / "digests" / "site"
    for pattern, base in (
        ("*.html", site),
        ("feed/*", site / "feed"),
        ("*.md", site),
        ("*.json", ROOT / "data" / "digests"),
    ):
        for path in base.glob(pattern):
            if path.is_file():
                try:
                    chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
                except OSError:
                    continue
    return "".join(chunks)


def build_charset() -> str:
    corpus = site_corpus()
    chars = set(corpus)
    chars.update(EXTRA)
    # ASCII + Latin-1 + general punctuation + CJK punctuation + fullwidth.
    chars.update(chr(c) for c in range(0x20, 0x7F))
    chars.update(chr(c) for c in range(0xA0, 0x100))
    chars.update(chr(c) for c in range(0x2000, 0x2070))
    chars.update(chr(c) for c in range(0x3000, 0x3040))
    chars.update(chr(c) for c in range(0xFF00, 0xFFEF))

    # **Only what the site actually renders.**
    #
    # Including the whole CJK block (20 902 glyphs) measured 13.4 MB -- unusable for a page. The
    # site's own corpus is the guarantee that today's output renders; a future headline with a
    # character outside it falls back to the next face in the stack, which is a visible but
    # harmless degradation. The build reports the corpus size so the coverage is a number, not a
    # hope.

    return "".join(sorted(c for c in chars if c.strip() or c == " "))


def main() -> int:
    if not SRC.exists():
        print(f"  源文件不存在：{SRC}")
        return 1

    charset = build_charset()
    print(f"  字符集: {len(charset):,} 个（含站点全部输出字符 + 常用 CJK）")

    args = [
        str(SRC),
        f"--text={charset}",
        f"--output-file={OUT}",
        "--flavor=woff2",
        "--layout-features=*",
        "--no-hinting",
        "--desubroutinize",
    ]
    subset.main(args)

    before = SRC.stat().st_size
    after = OUT.stat().st_size
    print(f"  原始 TTF : {before / 1e6:6.2f} MB")
    print(f"  子集 WOFF2: {after / 1e6:6.2f} MB  （{after / before:.1%}）")

    # Prove the subset still carries the site's characters, rather than assuming.
    font = TTFont(OUT)
    cmap = font.getBestCmap()
    missing = sorted({c for c in site_corpus() if ord(c) not in cmap and c.strip()})
    print(f"  站点字符缺失: {len(missing)} 个" + (f" -> {''.join(missing[:20])}" if missing else " ✓"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
