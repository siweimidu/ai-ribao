import io, sys, re, time, urllib.request, json
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
for i in range(3):
    try:
        h = urllib.request.urlopen(urllib.request.Request("https://aihot.news/hot", headers=UA), timeout=60).read().decode("utf-8", "replace")
        break
    except Exception as e:
        h = ""
        time.sleep(3)

print("  bytes=%d" % len(h))
open(r"C:\Users\35238\AppData\Local\Temp\hot.html", "w", encoding="utf-8").write(h)

for pat, label in ((r'"rank",(\d+)', "comma rank"), (r'"rank":(\d+)', "colon rank"),
                   (r'"heat",([0-9.]+)', "comma heat"), (r'"heat":([0-9.]+)', "colon heat")):
    print("  %-12s %d" % (label, len(re.findall(pat, h))))