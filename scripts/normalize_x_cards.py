"""把卡片统一成横版同高的规格。

卡片自带高度：短帖 600 上下，长帖能到 2400。直接并排会让页面长得没边，也对不齐。

这里的做法是**等比缩放后居中补边**，不裁切：
  · 裁切会把正文后半段切掉，读者拿到的是半条消息；
  · 缩放至少保住全部文字，只是长帖的字会变小；
  · 补边用的是卡片自己的底色，看起来是同一套版式，不是拼上去的。

规格固定为 1200×900（4:3），和参考站那种横版卡片一致。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image

CARD_W = 1200
CARD_H = 900


def _background(img: Image.Image) -> tuple[int, int, int]:
    """卡片自己的底色：取左上角像素，比写死白色更耐主题变化。"""
    return img.convert("RGB").getpixel((2, 2))


def normalize(path: Path, *, width: int = CARD_W, height: int = CARD_H) -> tuple[int, int]:
    """把一张卡片放进 width×height 的画面里，等比缩放，居中补边。"""
    with Image.open(path) as raw:
        img = raw.convert("RGB")
        box = _background(img)
        ratio = min(width / img.width, height / img.height)
        scaled = img.resize(
            (max(1, round(img.width * ratio)), max(1, round(img.height * ratio))),
            Image.LANCZOS,
        )
        canvas = Image.new("RGB", (width, height), box)
        canvas.paste(scaled, ((width - scaled.width) // 2, (height - scaled.height) // 2))
        canvas.save(path, "PNG", optimize=True)
        return canvas.size


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    root = Path("data/digests/site/assets/x")
    for png in sorted(root.glob("*.png")):
        before = Image.open(png).size
        after = normalize(png)
        print("  %-22s %sx%s -> %sx%s" % (png.name, before[0], before[1], after[0], after[1]))
