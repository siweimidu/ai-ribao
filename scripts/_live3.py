import io, sys, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

v = int(time.time())
base = "https://siweimidu.github.io/ai-ribao/"
pages = ["2026-10-14.html", "2026-10-15.html", "2026-10-16.html", "2026-10-17.html", "tibo.html"]
for name in pages:
    try:
        r = urllib.request.Request(base + name + "?v=%d" % v, headers={"User-Agent": "Mozilla/5.0"})
        h = urllib.request.urlopen(r, timeout=30).read().decode("utf-8", "replace")
    except Exception as e:
        print("  %-18s ERROR %s" % (name, e));
        continue
    print("  %-18s 本期说明=%s  首帧主题脚本=%s" % (name, "本期说明" in h, "aidaily-theme" in h))
