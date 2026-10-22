import io, sys, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
h = open(r"C:\Users\35238\AppData\Local\Temp\hot.html", encoding="utf-8").read()

cards = re.findall(r'<article class="card[^"]*"[^>]*>([\s\S]*?)</article>', h)
print("  卡片 %d" % len(cards))
print()

for i, c in enumerate(cards, 1):
    # The headline is the first <h2>/<h3> or the longest plain link text.
    heads = re.findall(r"<h[23][^>]*>([\s\S]*?)</h[23]>", c)
    no = re.search(r"NO\.<!-- -->(\d{1,2})", c)
    trend = "持平" if "持平" in c else (re.search(r"[↑↓]", c).group(0) if re.search(r"[↑↓]", c) else "?")
    pct = re.search(r"(\d{1,3})\s*<!-- -->\s*%", c) or re.search(r"(\d{1,3})\s*%", c)
    print("  #%s  no=%s trend=%s pct=%s" % (i, no.group(1) if no else "?", trend, pct.group(1) if pct else "-"))
    for hd in heads[:2]:
        print("      h: %s" % " ".join(re.sub(r"<[^>]+>", " ", hd).split())[:80])
    links = re.findall(r'href="(/items/[^"]+)"', c)
    if links:
        print("      link: %s" % links[0])
    print()