import io, json, sys
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

root = Path(r"D:\Code\AI日报")
items = json.loads((root / "docs" / "demo-items.json").read_text(encoding="utf-8"))

cards = []
for i, it in enumerate(items, 1):
    img = ""
    if it["image"]:
        img = ('<a class="thumb" href="%s" target="_blank" rel="noopener noreferrer">' % it["url"]
               + '<img src="demo-media/%s" alt="" loading="lazy"></a>' % it["image"])
    kb = ("%d KB WebP" % (it.get("bytes", 0) // 1024)) if it["image"] else "无配图"
    cards.append(
        '<li class="item">'
        '<div class="head"><span class="no">%02d</span>' % i
        + '<h3><a href="%s" target="_blank" rel="noopener noreferrer">%s</a></h3></div>' % (it["url"], it["title"])
        + img
        + '<div class="meta"><span class="badge">多源交叉验证</span><span class="dim">%s</span></div>' % kb
        + '</li>'
    )

tpl = (root / "scripts" / "_demo_tpl.html").read_text(encoding="utf-8")
html = tpl.replace("<!--CARDS-->", chr(10).join(cards))
p = root / "docs" / "图文并茂-效果预览.html"
p.write_text(html, encoding="utf-8")
print("  写入 %s  (%.1f KB)" % (p.name, p.stat().st_size / 1024))