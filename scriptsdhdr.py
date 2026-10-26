import io, sys
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
p = Path('src/aidaily/http.py')
s = p.read_text(encoding='utf-8')
old = '        req_headers: dict[str, str] = {}' + chr(10) + '        if conditional and (v := self.validators.get(url)):' + chr(10) + '            req_headers.update(v)' + chr(10) + chr(10) + '        last_detail = ""'
assert s.count(old) == 1, s.count(old)
new = Path('scripts/hdr.txt').read_text(encoding='utf-8').rstrip()
p.write_text(s.replace(old, new, 1), encoding='utf-8')
print('  patched')