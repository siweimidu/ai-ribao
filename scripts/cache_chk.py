import io, sys, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

p = r"C:\Users\35238\AppData\Local\Temp\aihot_hot.html"
print("  存在: %s  size=%d" % (os.path.exists(p), os.path.getsize(p) if os.path.exists(p) else 0))
h = open(p, encoding="utf-8").read()
print("  长度: %d" % len(h))
print()
for k in ("rank", "heat", "sourceCount", "NO.", "hot"):
    print("  %-14s %d" % (k, h.count(k)))
print()
print("  前 300 字符:")
print("  %s" % " ".join(h[:300].split()))