import io, sys, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

h = open(r"C:\Users\35238\AppData\Local\Temp\aihot_hot.html", encoding="utf-8").read()
for k in ("heat", "trend", "sourceCount", "participantCount", "rank"):
    print("  %-20s %d" % (k, h.count(k)))
print()
# What DOES it contain? Look for event titles
titles = re.findall(r'"title":"([^"]{10,80})"', h)
print("  title 字段 %d 条，前 5:" % len(titles))
for t in titles[:5]:
    print("    %s" % t[:70])
print()
i = h.find("NO.")
print("  含 NO. 标记: %s" % (i >= 0))
if i >= 0:
    print("    %s" % " ".join(h[i:i+400].split())[:380])