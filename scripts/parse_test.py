import asyncio, io, sys
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import feedparser, httpx

FEEDS = [
    ("arXiv cs.AI", "http://export.arxiv.org/rss/cs.AI"),
    ("arXiv cs.CL", "http://export.arxiv.org/rss/cs.CL"),
    ("HF Blog", "https://huggingface.co/blog/feed.xml"),
    ("OpenAI Blog", "https://openai.com/blog/rss.xml"),
    ("Ahead of AI", "https://magazine.sebastianraschka.com/feed"),
    ("Interconnects", "https://www.interconnects.ai/feed"),
    ("MIT TR AI", "https://www.technologyreview.com/topic/artificial-intelligence/feed"),
    ("Latent Space", "https://www.latent.space/feed"),
    ("TWIML", "https://twimlai.com/feed/podcast/"),
    ("Practical AI", "https://changelog.com/practicalai/feed"),
]

async def main():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 (compatible; ai-daily/1.0)"}) as c:
        for label, u in FEEDS:
            try:
                r = await c.get(u)
                d = feedparser.parse(r.content)
                n = len(d.entries)
                title = (d.entries[0].get("title") or "")[:52] if n else ""
                print("  %-16s %3d 条  %s" % (label, n, title))
            except Exception as e:
                print("  %-16s X %s" % (label, str(e)[:46]))

asyncio.run(main())