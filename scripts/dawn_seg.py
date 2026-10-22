import io, sys, re, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
h = ""
for _ in range(3):
    try:
        h = urllib.request.urlopen(urllib.request.Request("https://dailydawn.dev/zh/2026-10-22", headers=UA), timeout=45).read().decode("utf-8", "replace")
        break
    except Exception:
        time.sleep(2)

# Take the first section: does it contain a headline + body + link?
i = h.find("认知调试")
seg = h[max(0, i-400):i+2600]
txt = re.sub(r"<[^>]+>", "\n", seg)
lines = [x.strip() for x in txt.splitlines() if x.strip()]
print("  === 第一段（认知调试）附近 ====")
for x in lines[:30]:
    print("  %s" % x[:92])