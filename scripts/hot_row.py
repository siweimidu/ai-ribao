import io, sys, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
h = open(r"C:\Users\35238\AppData\Local\Temp\hot.html", encoding="utf-8").read()

cards = re.findall(r'<article class="card[^"]*"[^>]*>([\s\S]*?)</article>', h)
print("  卡片 %d 个" % len(cards))

# Each card: NO. NN, a trend chip (持平 / ↑ 15 % / ↓ 12 %), then the headline and summary.
ROW = re.compile(
    r"NO\.<!-- -->(\d{1,2}).*?"
    r"(持平|[↑↓]<!-- -->\s*(\d+)\s*%).*?"
    r"<h3[^>]*>(.*?)</h3>",
    re.S,
)
for i, c in enumerate(cards, 1):
    m = ROW.search(c)
    if m:
        print("  #%s trend=%s %s" % (m.group(1), m.group(2)[:12], re.sub(r"<[^>]+>", "", m.group(4))[:56]))
    else:
        txt = " ".join(re.sub(r"<[^>]+>", " ", c).replace("<!-- -->", "").split())
        print("  #%d 未匹配: %s" % (i, txt[:110]))