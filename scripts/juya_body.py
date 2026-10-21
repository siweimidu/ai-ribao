import io, re, sys, urllib.request, datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0"}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=45).read().decode("utf-8", "replace")

# The juya feed carries ONE item per day. Its body is the whole issue.
b = get("https://daily.juya.uk/rss.xml")
ms = list(re.finditer(r"<item>([\s\S]*?)</item>", b))

items = []
for m in ms:
    x = m.group(1)
    t = re.search(r"<title>(?:<!\[CDATA\[)?([^<\]]+)", x)
    d = re.search(r"<pubDate>([^<]+)</pubDate>", x)
    desc = re.search(r"<description>(?:<!\[CDATA\[)?([\s\S]*?)</description>", x)
    items.append({
        "title": t.group(1).strip() if t else "",
        "date": d.group(1).strip() if d else "",
        "body": desc.group(1) if desc else "",
    })

print("  juya feed 有 %d 个 item（每天一条，正文即整期）" % len(items))
for it in items[:2]:
    print()
    print("    %s  |  %s" % (it["title"], it["date"]))
    print("    正文长度: %d" % len(it["body"]))
    txt = re.sub(r"<[^>]+>", "\n", it["body"])
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    print("    前 12 行：")
    for l in lines[:12]:
        print("      %s" % l[:76])