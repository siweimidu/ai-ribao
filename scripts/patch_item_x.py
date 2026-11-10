"""把 X 卡片渲染进条目本身，而不是另起一个栏位。"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

site = Path("src/aidaily/site.py")
s = site.read_text(encoding="utf-8")

# 1) 条目里插入卡片：紧跟在图片之后、元信息之前。
old_video = '''    _facts = event.unique_facts if isinstance(event.unique_facts, dict) else {}'''
new_video = '''    _facts = event.unique_facts if isinstance(event.unique_facts, dict) else {}
    # X 卡片长在条目里：读者看的是「Anthropic 发布 Fable 5.2」这条新闻，推文图是它的佐证，
    # 不是另一栏里的展品。
    x_card = (_facts.get("x_card") or [""])[0]
    x_url = (_facts.get("x_url") or [""])[0]
    x_html = ""
    if x_card:
        x_html = (
            '<figure class="item__x">'
            f'<a href="{esc(x_url) or "#"}" target="_blank" rel="noopener noreferrer">'
            f'<img src="assets/x/{esc(x_card)}" alt="原帖" loading="lazy" decoding="async">'
            "</a>"
            '<figcaption>原帖截图 · <a href="'
            + (esc(x_url) or "#")
            + '" target="_blank" rel="noopener noreferrer">打开 X</a></figcaption>'
            "</figure>"
        )'''
assert s.count(old_video) == 1, s.count(old_video)
s = s.replace(old_video, new_video, 1)

# 2) 把 x_html 放进条目模板：紧接在条目图片之后。
old_tpl = "{image_html}"
if s.count(old_tpl) >= 1:
    s = s.replace(old_tpl, "{image_html}{x_html}", 1)
    print("  模板已插入 x_html")
else:
    print("  WARN: 没找到 image_html 占位")

# 3) 不再渲染独立的「X 精选」栏位。
old_call = "    x_highlights = render_x_highlights()"
if s.count(old_call) == 1:
    s = s.replace(old_call, '    x_highlights = ""', 1)
    print("  独立栏位已关闭（卡片改挂在条目里）")

site.write_text(s, encoding="utf-8")
print("  site.py patched")

css = Path("site/assets/components.css")
style = '''

/* 条目里的 X 卡片。宽度跟正文列一致，高度按比例走；
   一屏放不下没关系 —— 它是佐证，读者可以跳过。 */
.item__x {
  margin: calc(var(--unit) * 2) 0;
  padding-left: calc(1.6em + var(--unit) * 3);
}
.item__x img {
  display: block;
  width: 100%;
  max-width: 640px;
  height: auto;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: #fff;
}
.item__x figcaption {
  margin-top: 6px;
  font-size: var(--fs-micro);
  color: var(--muted-fg);
}
.item__x figcaption a { color: var(--accent); text-decoration: none; }
.item__x figcaption a:hover { text-decoration: underline; }
'''
text = css.read_text(encoding="utf-8")
if ".item__x" not in text:
    css.write_text(text + style, encoding="utf-8")
    print("  CSS 已加 .item__x")
