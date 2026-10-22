import io, sys, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
h = open(r"C:\Users\35238\AppData\Local\Temp\hot.html", encoding="utf-8").read()

# Each hot entry is an <article class="card ..."> … </article>
cards = re.findall(r'<article class="card[^"]*"[^>]*>([\s\S]*?)</article>', h)
print("  article 卡片: %d" % len(cards))
print()
for i, c in enumerate(cards[:3], 1):
    txt = re.sub(r"<[^>]+>", " ", c)
    txt = " ".join(txt.replace("<!-- -->", "").split())
    print("  #%d %s" % (i, txt[:300]))
    print()

# Is there a data blob with heat?
i = h.find("heat")
print("  heat 处: %s" % " ".join(h[max(0,i-160):i+260].split())[:420])