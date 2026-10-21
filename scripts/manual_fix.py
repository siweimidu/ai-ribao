import io, json, subprocess, sys
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

root = Path(r"D:\Code\AI日报")
# Build a fixture items file the same way the test does.
sys.path.insert(0, str(root / "tests" / "integration"))

out = Path(r"C:\Users\35238\AppData\Local\Temp\fixtest2")
out.mkdir(exist_ok=True)

r = subprocess.run(
    [sys.executable, "-m", "aidaily", "run",
     "--from-items", str(root / "tests" / "integration" / "fixtures" / "items.jsonl"),
     "--out-dir", str(out), "--no-llm", "--no-deliver", "--no-env", "--allow-early"],
    capture_output=True, text=True, encoding="utf-8", cwd=str(root),
    env={"PYTHONPATH": str(root / "src"), "PYTHONIOENCODING": "utf-8", "PATH": ""},
)
print("  exit:", r.returncode)
print(r.stdout[-2500:])
if r.stderr.strip():
    print("  STDERR:", r.stderr[-800:])