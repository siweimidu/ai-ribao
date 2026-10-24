import asyncio, io, sys
sys.path.insert(0, r'D:\Code\AI日报\src')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from aidaily.http import HttpClient
from aidaily.fetchers.bilibili import BilibiliHotFetcher
from aidaily.models import SourceSpec

spec = SourceSpec(
    source_id='api:bilibili-hot-search',
    name='B站热搜',
    url='https://api.bilibili.com/x/web-interface/search/square?limit=50',
    normalized_url='https://api.bilibili.com/x/web-interface/search/square?limit=50',
    domain='api.bilibili.com',
    category='social',
    source_type='api',
    adapter='BilibiliHotFetcher',
)

async def main():
    async with HttpClient() as c:
        r = await BilibiliHotFetcher(c).fetch(spec)
        print('  verdict=%s  items=%d' % (r.verdict, len(r.items)))
        for it in r.items:
            print('    %s  heat=%s' % (it.title[:56], (it.metrics or {}).get('heat_score')))
            print('      url: %s' % it.url[:80])

asyncio.run(main())