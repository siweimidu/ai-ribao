import io, sys, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

h = open(r"C:\Users\35238\AppData\Local\Temp\aihot_hot.html", encoding="utf-8").read()

i = h.find("heat")
print("  heat 唯一出现处的上下文：")
print("  %s" % " ".join(h[max(0, i - 200):i + 400].split())[:560])
print()

# Count the rank markers and show a couple of full cards as text
for m in list(re.finditer(r"NO\.<!-- -->(\d+)", h))[:3]:
    seg = h[m.start():m.start() + 1400]
    txt = re.sub(r"<[^>]+>", " ", seg)
    txt = " ".join(txt.replace("<!-- -->", "").split())
    print("  NO.%s  %s" % (m.group(1), txt[:200]))
    print()