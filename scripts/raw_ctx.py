import io, sys, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

h = open(r"C:\Users\35238\AppData\Local\Temp\aihot_hot.html", encoding="utf-8").read()
i = h.find("rank")
print("  rank 首次出现在 %d" % i)
print("  原始上下文(repr):")
print("  %r" % h[max(0, i-60):i+120])