import io, re, sys, urllib.request, datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=45).read().decode("utf-8", "replace")

now = datetime.datetime.now(datetime.timezone.utc)
print("  现在 UTC: %s" % now.strftime("%Y-%m-%d %H:%M"))
print("  采集快照来自: 2026-10-20 23:10 UTC")
print()

feeds = [
    ("juya",      "https://daily.juya.uk/rss.xml"),
    ("ainewslog", "https://ainewslog.com/rss.xml"),
    ("hex2077",   "https://hex2077.dev/rss-zh-CN.xml"),
    ("dailydawn", "https://dailydawn.dev/feed.xml"),
    ("aibase",    "https://aibase.com"),
]

for name, url in feeds:
    try:
        body = get(url)
    except Exception as e:
        print("  %-10s 抓取失败 %s" % (name, str(e)[:45]))
        continue
    dates = re.findall(r"<(?:pubDate|published|updated|dc:date)>([^<]+)<", body)
    parsed = []
    for s in (d.strip() for d in dates):
        for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                t = datetime.datetime.strptime(s, fmt)
                if t.tzinfo is None:
                    t = t.replace(tzinfo=datetime.timezone.utc)
                parsed.append(t)
                break
            except ValueError:
                continue
    if not parsed:
        print("  %-10s 无日期" % name)
        continue
    parsed.sort(reverse=True)
    print("  %-10s 最新 %s  %.1f 小时前  共 %d 个日期" % (
        name, parsed[0].strftime("%m-%d %H:%M"), (now - parsed[0]).total_seconds() / 3600.0, len(parsed)))