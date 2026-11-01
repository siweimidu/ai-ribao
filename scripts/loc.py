import io, re, sys, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
L = pathlib.Path('src/aidaily/__main__.py').read_text(encoding='utf-8').splitlines()
for i, l in enumerate(L, 1):
    if re.search(r'_fetch_images\(|def cmd_run|def _analyze_async|run_now = |started_at|time\.monotonic', l):
        print('%5d: %s' % (i, l.strip()[:88]))