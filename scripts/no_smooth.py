from pathlib import Path
p = Path("site/assets/components.css")
s = p.read_text(encoding="utf-8")

# `scroll-behavior: smooth` on the TOC fights the per-frame paging: each scroll event issues a
# new smooth scroll that cancels the previous one, so the outline lags and stutters instead of
# following the article. The paging code already interpolates by setting scrollTop directly.
old = """    overscroll-behavior: contain;
    scroll-behavior: smooth;"""
new = """    overscroll-behavior: contain;"""
assert s.count(old) == 1
s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")
print("smooth removed from toc")