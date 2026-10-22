import io, sys, re, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

def get(url):
    req = urllib.request.Request(url, headers=UA)
    h = urllib.request.urlopen(req, timeout=45).read().decode("utf-8", "replace")
    return h

print("  === hex2077.dev/docs ===")
try:
    h = get("https://hex2077.dev/docs")
    print("    bytes=%d" % len(h))
    feeds = re.findall(r'href="([^"]*(?:rss|atom|feed)[^"]*)"', h, re.I)
    print("    feed 链接: %s" % sorted(set(feeds))[:5])
    links = sorted(set(re.findall(r'href="(/docs/[^"#?]+)"', h)))[:8]
    print("    /docs/ 链接: %s" % links)
except Exception as e:
    print("    ERR %s" % str(e)[:60])

print()
print("  === aihot.news/all ===")
try:
    h = get("https://aihot.news/all")
    print("    bytes=%d" % len(h))
    feeds = re.findall(r'href="([^"]*(?:rss|atom|feed)[^"]*)"', h, re.I)
    print("    feed 链接: %s" % sorted(set(feeds))[:5])
except Exception as e:
    print("    ERR %s" % str(e)[:60])