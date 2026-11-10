"""卡片只统一宽度，高度保持自然比例。

强制同高会把内容少的卡片补出大片空白（实测 Google/Higgsfield 两页下面空了一千多像素），
而内容多的又会被压缩。宽度统一 + 自然高度，页面看起来更满、字也更大；两列顶部对齐即可。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

CARD_W = 1080


def normalize(path: Path, *, width: int = CARD_W) -> tuple[int, int]:
    """按宽度统一，高度按比例走 —— 不补边、不裁切。"""
    with Image.open(path) as raw:
        img = raw.convert("RGB")
        if img.width == width:
            return img.size
        height = max(1, round(img.height * width / img.width))
        img.resize((width, height), Image.LANCZOS).save(path, "PNG", optimize=True)
        return (width, height)


if __name__ == "__main__":
    import io
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    root = Path("data/digests/site/assets/x")
    for png in sorted(root.glob("*.png")):
        before = Image.open(png).size
        after = normalize(png)
        print("  %-22s %sx%s -> %sx%s" % (png.name, before[0], before[1], after[0], after[1]))
