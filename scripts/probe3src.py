import io, sys, json, urllib.request
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import feedparser

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

feeds = {
    "juya":    "https://daily.juya.uk/rss.xml",
    "hex2077": "https://hex2077.dev/docs",
    "aihot-all":"https://aihot.news/all",
    "aihot-hot":"https://aihot.news/hot",
}

for name, url in feeds.items():
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()
        ct = "?"
        try:
            p = feedparser.parse(raw)
            n = len(p.entries or [])
            print("  %-10s bytes=%-7d feed=%s entries=%d" % (name, len(raw), bool(p.entries), n))
            if p.entries:
                e = p.entries[0]
                print("      title=%s" % (e.get("title") or "")[:60])
                print("      keys =%s" % sorted(e.keys())[:12])
                print("      link =%s" % (e.get("link") or "")[:70])
        except Exception as pe:
            print("  %-10s bytes=%d parse-err %s" % (name, len(raw), str(pe)[:40]))
    except Exception as e:
        print("  %-10s ERR %s" % (name, str(e)[:60]))