import io, sys, re, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

h = open(r"C:\Users\35238\AppData\Local\Temp\aihot_hot.html", encoding="utf-8").read()
print("  bytes=%d" % len(h))

i = h.find('"sourceCount"')
print("  sourceCount at %d" % i)
print()
print("  === 该处前后 900 字符 ===")
print(" ".join(h[max(0, i - 700):i + 200].split())[:900])