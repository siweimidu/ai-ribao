import io, json, re, subprocess, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

rid = "39547122479"
for _ in range(50):
    r = subprocess.run(["gh", "run", "view", rid, "--repo", "siweimidu/ai-ribao",
                        "--json", "status,conclusion"], capture_output=True, text=True, encoding="utf-8")
    try:
        d = json.loads(r.stdout)
    except ValueError:
        time.sleep(15); continue
    if d.get("status") == "completed":
        print("  结果: %s" % d.get("conclusion"))
        break
    time.sleep(15)
else:
    print("  仍在运行（超过 12 分钟）")