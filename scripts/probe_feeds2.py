import io, sys, re, urllib.request
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import feedparser
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

for name, url in (("hex2077", "https://hex2077.dev/rss-zh-CN.xml"), ("aihot", "https://aihot.news/feed.xml")):
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45).read()
        p = feedparser.parse(raw)
        print("  === %s  bytes=%d  entries=%d ===" % (name, len(raw), len(p.entries or [])))
        for e in (p.entries or [])[:2]:
            print("    title: %s" % (e.get("title") or "")[:60])
            print("    link : %s" % (e.get("link") or "")[:64])
            body = e.get("content", [{}])[0].get("value", "") if e.get("content") else (e.get("summary") or "")
            print("    body : %d chars" % len(body))
            print("    head : %s" % " ".join(re.sub(r"<[^>]+>", " ", body).split())[:180])
            print()
    except Exception as e:
        print("  %s ERR %s" % (name, str(e)[:60]))