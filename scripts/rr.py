from pathlib import Path
p = Path("scripts/rerender_site.py")
s = p.read_text(encoding="utf-8")

old = """    site = write_site(
        digest, deep, out_dir,
        site_url=site_url, insights=insights, items_by_id=items, tibo=tibo,
        sources=load_sources(),
    )"""

new = """    # Repository metadata for the GitHub cards. Re-rendering is an offline operation, so this
    # is best-effort: without it the repository stories fall back to a plain headline, which is
    # exactly what they looked like before the cards existed.
    repo_meta: dict[str, dict] = {}
    try:
        import asyncio as _asyncio

        from aidaily.github_meta import fetch_many, repo_of

        slugs = {
            repo_of(url)
            for event in digest.top_events
            for url in (event.all_urls or [])[:3]
        }
        slugs.discard(None)
        if slugs:
            repo_meta = _asyncio.run(fetch_many(sorted(slugs)))
    except Exception:
        repo_meta = {}

    site = write_site(
        digest, deep, out_dir,
        site_url=site_url, insights=insights, items_by_id=items, tibo=tibo,
        sources=load_sources(), repo_meta=repo_meta,
    )"""

assert s.count(old) == 1, s.count(old)
s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")
print("rerender_site wired")