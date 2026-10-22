import io, sys, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
h = open(r"C:\Users\35238\AppData\Local\Temp\hot.html", encoding="utf-8").read()
print("  bytes=%d" % len(h))
for k in ("heat", "rank", "NO.", "sourceCount", "热度", "story", "events"):
    print("  %-14s %d" % (k, h.count(k)))
print()
i = h.find("NO.")
print("  NO. 处: %s" % (" ".join(h[max(0,i-200):i+300].split())[:420] if i >= 0 else "无"))
print()
scripts = re.findall(r'src="(/assets/[^"]+)"', h)
print("  script 数: %d" % len(scripts))
for s2 in scripts[:6]:
    print("    %s" % s2)