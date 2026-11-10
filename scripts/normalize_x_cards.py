"""统一尺寸：按宽度缩放，高度补边到同一值（不压缩短卡）。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

CARD_W = 1080
CARD_H = 1400


def _background(img: Image.Image) -> tuple[int, int, int]:
    """卡片自己的底色：取左上角像素，比写死白色更耐主题变化。"""
    return img.convert("RGB").getpixel((2, 2))


def normalize(path: Path, *, width: int = CARD_W, height: int = CARD_H) -> tuple[int, int]:
    """把一张卡片放进 width×height 的画面里。

    先按宽度缩放 —— 单页卡原生 1200 宽，缩到 1080 后正文仍是原生大小；
    只有当它比画布还高时才按高度再缩，这一步很少触发，因为超高的帖子在分流时已经改成跨页。
    高度不足的补边，补的是卡片自己的底色。
    """
    with Image.open(path) as raw:
        img = raw.convert("RGB")
        box = _background(img)
        ratio = width / img.width
        if img.height * ratio > height:
            ratio = min(ratio, height / img.height)
        scaled = img.resize(
            (max(1, round(img.width * ratio)), max(1, round(img.height * ratio))),
            Image.LANCZOS,
        )
        canvas = Image.new("RGB", (width, height), box)
        canvas.paste(scaled, ((width - scaled.width) // 2, (height - scaled.height) // 2))
        canvas.save(path, "PNG", optimize=True)
        return canvas.size


if __name__ == "__main__":
    import io
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    root = Path("data/digests/site/assets/x")
    for png in sorted(root.glob("*.png")):
        before = Image.open(png).size
        after = normalize(png)
        print("  %-22s %sx%s -> %sx%s" % (png.name, before[0], before[1], after[0], after[1]))
