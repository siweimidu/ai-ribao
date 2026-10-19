import io, re, subprocess, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
root = r"D:\Code\AI日报"
r = subprocess.run(["gh", "run", "view", "39263568833", "--repo", "siweimidu/ai-ribao", "--log"],
                   capture_output=True, cwd=root)
text = re.sub(r"\x1b\[[0-9;]*m", "", r.stdout.decode("utf-8", "replace"))
for line in text.splitlines():
    body = line.split("\t")[-1].strip()
    if re.search(r"today=|events=|last_scheduled=|already has|re-trigger|leaving it alone", body):
        print("  " + body[:140])