import io, sys, json
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from aidaily.designation import is_roundup

tests = [
    "AI 早报 2026-10-22",
    "何夕2077 AI 深度信号周报 2026 W42",
    "2026-10-22",
    "Claude Duet 开放研究预览，主动提醒并在后台办事",
]
for t in tests:
    print("  is_roundup=%-5s  %s" % (is_roundup(t), t[:60]))