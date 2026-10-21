import io, re, sys, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0"}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=45).read().decode("utf-8", "replace")

print("  === dailydawn 最新一期 ===")
b = get("https://dailydawn.dev/feed.xml")
for m in list(re.finditer(r"<item>([\s\S]*?)</item>", b))[:2]:
    x = m.group(1)
    t = re.search(r"<title>(?:<!\[CDATA\[)?([^<\]]+)", x)
    d = re.search(r"<pubDate>([^<]+)</pubDate>", x)
    desc = re.search(r"<description>(?:<!\[CDATA\[)?([\s\S]{0,400})", x)
    print("    %s" % (t.group(1).strip()[:60] if t else "?"))
    print("        %s" % (d.group(1).strip() if d else "?"))
    if desc:
        txt = re.sub(r"<[^>]+>", " ", desc.group(1))
        txt = re.sub(r"\s+", " ", txt).strip()
        print("        %s" % txt[:170])
print()

print("  === juya 最新一期 ===")
b = get("https://daily.juya.uk/rss.xml")
ms = list(re.finditer(r"<item>([\s\S]*?)</item>", b))
print("    共 %d 个 item" % len(ms))
for m in ms[:1]:
    x = m.group(1)
    t = re.search(r"<title>(?:<!\[CDATA\[)?([^<\]]+)", x)
    d = re.search(r"<pubDate>([^<]+)</pubDate>", x)
    print("    %s" % (t.group(1).strip()[:60] if t else "?"))
    print("        %s" % (d.group(1).strip() if d else "?"))