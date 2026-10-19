import io, os, sys, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0"}
out = r"C:\Users\35238\AppData\Local\Temp\aihot_shots"
os.makedirs(out, exist_ok=True)

urls = {
    "shots-light.png": "https://raw.githubusercontent.com/siweimidu/AIHOT/main/docs/assets/shots-light.png",
    "how-light.png": "https://raw.githubusercontent.com/siweimidu/AIHOT/main/docs/assets/how-light.png",
    "cluster-light.png": "https://raw.githubusercontent.com/siweimidu/AIHOT/main/docs/assets/cluster-light.png",
    "perf-light.png": "https://raw.githubusercontent.com/siweimidu/AIHOT/main/docs/assets/perf-light.png",
}
for name, url in urls.items():
    try:
        data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
        p = os.path.join(out, name)
        open(p, "wb").write(data)
        print("  %-20s %d bytes" % (name, len(data)))
    except Exception as e:
        print("  %-20s ERROR %s" % (name, str(e)[:60]))