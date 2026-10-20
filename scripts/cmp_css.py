import io, re, sys
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

src = Path(r"D:\Code\AI日报\site\assets\components.css").read_text(encoding="utf-8")
out = Path(r"D:\Code\AI日报\data\digests\site\assets\components.css").read_text(encoding="utf-8")
print("  源文件: %d bytes, sticky=%d, visible=%d" % (
    len(src), src.count("position: sticky"), src.count("overflow-y: visible")))
print("  产物:   %d bytes, sticky=%d, visible=%d" % (
    len(out), out.count("position: sticky"), out.count("overflow-y: visible")))
print()
m1 = re.findall(r"[^{}]*\.toc[^{}]*\{[^}]*overflow-y[^}]*\}", out)
print("  产物里的 toc 规则：")
for x in m1:
    print("    " + " ".join(x.split())[:150])