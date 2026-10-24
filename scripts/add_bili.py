import io, sys
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

p = Path(r'D:\Code\AI日报\sources\local.yaml')
s = p.read_text(encoding='utf-8')
block = Path(r'D:\Code\AI日报\scripts\bili_yaml.txt').read_text(encoding='utf-8').rstrip()

if 'bilibili-hot-search' in s:
    print('  already present')
else:
    s = s.rstrip(chr(10)) + chr(10) + block + chr(10)
    p.write_text(s, encoding='utf-8')
    print('  added')