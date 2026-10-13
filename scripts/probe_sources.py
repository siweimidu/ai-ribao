#!/usr/bin/env python3
"""Probe every source in sources/registry.yaml and write a real health report.

This is the step that produces the first honest answer to "how many of the 100
sources actually work". Nothing here is estimated: every verdict carries the
HTTP status, the parsed item count, or the exception that was actually raised.

Verdicts
  healthy           HTTP 2xx and the payload parsed with >=1 item
  degraded          HTTP 2xx but parsed 0 items, or a slow/partial response
  dead              4xx/5xx, DNS failure, TLS failure, or unparseable payload
  needs_credential  skipped: the source requires a token/cookie we do not have
  disabled          present in the registry but not wired up (enabled: false)
  unverified        deliberately not probed (e.g. endpoints driven by a library)

A control URL is probed first: when the control itself fails, local network
problems (proxy/TUN) are reported as such instead of blaming every source.

Stdlib + PyYAML + feedparser only.
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "sources" / "registry.yaml"
HEALTH = ROOT / "data" / "state" / "health.jsonl"
REPORT = ROOT / "docs" / "HEALTH_REPORT.md"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
CTX = ssl.create_default_context()
CONTROL_URL = "https://example.com"

# Hosts that are not directly fetchable: a library talks to an internal API.
# Kept in the registry (never deleted) but reported as unverified, not as dead.
SKIP_HOSTS = {"trends.google.com"}

# HTTP codes that mean "the resource exists but refuses automated access" rather
# than "the resource is gone". Conflating the two would send us chasing the wrong fix.
BLOCKED_CODES = {401, 403, 429}


def http_verdict(source: dict, status, err, detail: str = "") -> dict:
    if status in BLOCKED_CODES:
        return verdict(
            source, "blocked", http=status,
            detail=f"{err or ''} — 源存在但拒绝自动访问：需要凭证或改用别的入口（Reddit 的 HTML 入口同样已被登录墙拦截）",
        )
    return verdict(source, "dead", http=status, detail=err or f"HTTP {status}")


def fetch(url: str, timeout: int = 20, tries: int = 2):
    """Return (status, body_bytes, ctype, error, final_url). Never raises."""
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                return r.status, r.read(2_000_000), r.headers.get("Content-Type", ""), None, r.geturl()
        except urllib.error.HTTPError as e:
            # HTTP errors are definitive for 4xx; retry only 5xx.
            if e.code < 500:
                return e.code, b"", "", f"HTTP {e.code} {e.reason}", url
            last = f"HTTP {e.code} {e.reason}"
        except Exception as exc:  # noqa: BLE001 - a probe must never crash the run
            last = f"{type(exc).__name__}: {exc}"
        if attempt == 0:
            time.sleep(2)
    return None, b"", "", last, url


def _access_wall(html: str) -> str | None:
    """Detect an access wall served with HTTP 200.

    This exists because the first version of this probe reported `old.reddit.com` as
    **healthy**: it answers 200 with a 330 KB login page, which passes any check based
    on status code and body size. A wall is not a feed.
    """
    head = html[:30_000].lower()
    if 'data-fullname="t3_' in html or 'class="thing' in html or "shreddit-post" in head:
        return None                                   # real listing content
    if "/login/" in head and "lor2" in head:
        return "重定向到登录页（reason=lor2），匿名访问已关闭"
    if "whoa there" in head or "you've been blocked" in head or "are you a robot" in head:
        return "反爬拦截页"
    return None


def _newest_entry(feed) -> str:
    """Newest timestamp across all entries, as ISO-8601 UTC.

    Do NOT trust entry order: several feeds publish oldest-first -- see the comment
    in ai-daily-sources/scripts/collect.py about ainewslog ("Feed is ordered
    oldest-first ... never trust ordering"). Reading entries[0] would claim a live
    feed is months stale.
    """
    best = None
    for e in feed.entries:
        for field in ("published_parsed", "updated_parsed"):
            t = e.get(field)
            if t and (best is None or t > best):
                best = t
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", best) if best else ""


def probe_feed(source: dict) -> dict:
    import feedparser

    status, body, ctype, err, final = fetch(source["url"], source["timeout_s"])
    if err and status is None:
        return verdict(source, "dead", detail=err)
    feed = feedparser.parse(body)
    n = len(feed.entries)
    newest = _newest_entry(feed)
    if n > 0:
        return verdict(source, "healthy", http=status, items=n, newest=newest,
                       detail=f"{feed.feed.get('title', '')[:60]}")
    if status and status < 400:
        bozo = getattr(feed, "bozo", 0)
        return verdict(source, "degraded", http=status, items=0,
                       detail=f"parsed OK but 0 entries (bozo={bozo}) {str(getattr(feed,'bozo_exception',''))[:80]}")
    return http_verdict(source, status, err, "no entries")


def probe_jsonfeed(source: dict) -> dict:
    status, body, ctype, err, final = fetch(source["url"], source["timeout_s"])
    if err and status is None:
        return verdict(source, "dead", detail=err)
    try:
        doc = json.loads(body or b"")
    except Exception as exc:  # noqa: BLE001
        return verdict(source, "dead", http=status, detail=f"JSON parse failed: {type(exc).__name__}")
    items = doc.get("items") or []
    newest = items[0].get("date_published", "") if items else ""
    v = "healthy" if items else "degraded"
    return verdict(source, v, http=status, items=len(items), newest=newest,
                   detail=f"title={str(doc.get('title',''))[:50]}")


def probe_api(source: dict) -> dict:
    """APIs need a payload sanity check, not just a 200."""
    status, body, ctype, err, final = fetch(source["url"], source["timeout_s"])
    if err and status is None:
        return verdict(source, "dead", detail=err)
    if status and status >= 400:
        return http_verdict(source, status, err)
    size = len(body or b"")
    if size == 0:
        return verdict(source, "degraded", http=status, items=0, detail="HTTP 2xx but empty body")

    # Some sources are typed "api" in the audit ledger but actually return a feed
    # (e.g. the Google News RSS search endpoint). Counting only JSON arrays would
    # report a perfectly good feed as degraded, so sniff the content type first.
    head = (body or b"")[:200].lstrip()
    looks_like_feed = (
        "xml" in (ctype or "").lower()
        or head.startswith(b"<?xml")
        or head.startswith(b"<rss")
        or head.startswith(b"<feed")
        or head.startswith(b"<")
    )
    if looks_like_feed:
        import feedparser

        feed = feedparser.parse(body)          # parse BYTES: the XML prolog is authoritative
        n = len(feed.entries)
        newest = _newest_entry(feed)
        if n:
            return verdict(source, "healthy", http=status, items=n, newest=newest,
                           detail=f"feed: {feed.feed.get('title', '')[:50]}")
        return verdict(source, "degraded", http=status, items=0,
                       detail=f"xml {size}B but 0 entries")

    items = 0
    kind = "unknown"
    if body[:1] in (b"[", b"{"):
        try:
            doc = json.loads(body)
            if isinstance(doc, list):
                items, kind = len(doc), "json-list"
            elif isinstance(doc, dict):
                for key in ("hits", "items", "results", "data", "articles", "stories"):
                    if isinstance(doc.get(key), list):
                        items, kind = len(doc[key]), f"json.{key}"
                        break
                else:
                    items, kind = 1, "json-object"
        except Exception:  # noqa: BLE001
            kind = "json-unparseable"
    else:
        kind = ctype.split(";")[0] or "binary"
    v = "healthy" if items > 0 else "degraded"
    return verdict(source, v, http=status, items=items, detail=f"{kind}, {size}B")


def probe_scrape(source: dict) -> dict:
    status, body, ctype, err, final = fetch(source["url"], source["timeout_s"])
    if err and status is None:
        return verdict(source, "dead", detail=err)
    if status and status >= 400:
        return http_verdict(source, status, err)
    html = (body or b"").decode("utf-8", "replace")
    wall = _access_wall(html)
    if wall:
        # HTTP 200 is not evidence of a working source -- see _access_wall.
        return verdict(source, "blocked", http=status, items=0,
                       detail=f"{wall}；最终 URL {final}"[:200])
    size = len(body or b"")
    v = "healthy" if size > 2000 else "degraded"
    return verdict(source, v, http=status, items=0, detail=f"html {size}B")


def verdict(source: dict, v: str, http=None, items=0, newest: str = "", detail: str = "") -> dict:
    return {
        "source_id": source["source_id"],
        "name": source["name"],
        "url": source["url"],
        "domain": source["domain"],
        "category": source["category"],
        "source_type": source["source_type"],
        "repositories": source["repositories"],
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "verdict": v,
        "http_status": http,
        "items": items,
        "newest_published": newest,
        "detail": detail[:200],
    }


PROBES = {"rss": probe_feed, "atom": probe_feed, "jsonfeed": probe_jsonfeed,
          "api": probe_api, "scrape": probe_scrape}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit", type=int, default=0, help="probe only the first N enabled sources")
    args = ap.parse_args()

    doc = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    sources = doc["sources"]

    print(f"registry: {len(sources)} unique sources")

    # --- control probe: separate "my network is broken" from "the source is dead"
    cstatus, _, _, cerr, _cfinal = fetch(CONTROL_URL, 15, 1)
    control_ok = cstatus is not None and cstatus < 400
    print(f"control probe {CONTROL_URL} -> {cstatus or cerr} ({'ok' if control_ok else 'FAILED'})")
    if not control_ok:
        print("!! control URL failed: local network/proxy problem. Verdicts below are unreliable.")

    def probeable(s: dict) -> bool:
        return s["health_status"] == "unverified" and s["domain"] not in SKIP_HOSTS

    todo = [s for s in sources if probeable(s)]
    skipped = [s for s in sources if not probeable(s)]
    if args.limit:
        todo = todo[: args.limit]
    print(f"to probe: {len(todo)}  not probed (credential/disabled/library-driven): {len(skipped)}")

    results = []
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(PROBES[s["source_type"]], s): s for s in todo}
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                results.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                results.append(verdict(s, "dead", detail=f"probe crashed: {type(exc).__name__}: {exc}"))
    elapsed = time.monotonic() - t0

    for s in skipped:
        results.append(
            {
                "source_id": s["source_id"], "name": s["name"], "url": s["url"],
                "domain": s["domain"], "category": s["category"], "source_type": s["source_type"],
                "repositories": s["repositories"],
                "probed_at": datetime.now(timezone.utc).isoformat(),
                "verdict": s["health_status"], "http_status": None, "items": 0,
                "newest_published": "",
                "detail": (
                    f"requires {s['needs_credential']}" if s["needs_credential"]
                    else ("由代码库驱动（非该 URL 直接抓取）" if s["domain"] in SKIP_HOSTS
                          else "present in registry but not wired up")
                ),
            }
        )

    results.sort(key=lambda r: (r["verdict"] != "healthy", r["domain"], r["source_id"]))

    HEALTH.parent.mkdir(parents=True, exist_ok=True)
    with HEALTH.open("a", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    by_domain: dict[str, list[str]] = {}
    for r in results:
        by_domain.setdefault(r["domain"], []).append(r["verdict"])

    lines = [
        "# 信息源健康报告（真实探测结果）",
        "",
        f"探测时间：{datetime.now(timezone.utc).astimezone().isoformat()}　耗时 {elapsed:.1f}s　并发 {args.workers}",
        f"控制组 `{CONTROL_URL}`：**{'正常' if control_ok else '失败（本地网络/代理问题，结论不可靠）'}**",
        "",
        "> 本报告由 `scripts/probe_sources.py` 真实联网探测生成。每条判定都带 HTTP 状态、解析到的条目数或真实异常，无一条是估算。",
        "",
        "## 总览",
        "",
        "| 判定 | 数量 | 含义 |",
        "|---|---|---|",
        f"| healthy | {counts.get('healthy', 0)} | HTTP 2xx 且解析出 ≥1 条 |",
        f"| degraded | {counts.get('degraded', 0)} | HTTP 2xx 但解析 0 条 / 响应异常 |",
        f"| blocked | {counts.get('blocked', 0)} | 401/403/429：源存在但拒绝自动访问 |",
        f"| dead | {counts.get('dead', 0)} | DNS/TLS 失败、4xx/5xx 或无法解析 |",
        f"| needs_credential | {counts.get('needs_credential', 0)} | 需 token/cookie，未探测 |",
        f"| disabled | {counts.get('disabled', 0)} | 存在于注册表但未启用（示例/未注册适配器） |",
        f"| unverified | {counts.get('unverified', 0)} | 有意未探测 |",
        f"| **合计** | **{len(results)}** | |",
        "",
    ]

    for bucket, title in (
        ("blocked", "⛔ 被拒绝自动访问（源存在，需换抓取方式或补凭证）"),
        ("dead", "❌ 失效（配置保留，需要修复）"),
        ("degraded", "⚠️ 降级"),
    ):
        rows = [r for r in results if r["verdict"] == bucket]
        if not rows:
            continue
        lines += [f"## {title}", "", "| 源 | 域名 | 类型 | HTTP | 详情 |", "|---|---|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['name'][:44]} | {r['domain']} | {r['source_type']} | {r['http_status'] or '-'} | {r['detail'][:90]} |")
        lines.append("")

    lines += ["## ✅ 健康源", "", "| 源 | 域名 | 类型 | 条目数 | 最新发布时间 |", "|---|---|---|---|---|"]
    for r in [x for x in results if x["verdict"] == "healthy"]:
        lines.append(f"| {r['name'][:44]} | {r['domain']} | {r['source_type']} | {r['items']} | {(r['newest_published'] or '-')[:31]} |")
    lines.append("")

    nr = [r for r in results if r["verdict"] == "needs_credential"]
    if nr:
        lines += ["## 🔑 需要凭证（未探测）", "", "| 源 | 域名 | 所需凭证 |", "|---|---|---|"]
        for r in nr:
            lines.append(f"| {r['name'][:44]} | {r['domain']} | {r['detail']} |")
        lines.append("")

    ds = [r for r in results if r["verdict"] == "disabled"]
    if ds:
        lines += ["## ⏸ 已禁用 / 未接入（按策略保留，不删除）", "", "| 源 | 域名 | 说明 |", "|---|---|---|"]
        for r in ds:
            lines.append(f"| {r['name'][:44]} | {r['domain']} | {r['detail'][:70]} |")
        lines.append("")

    uv = [r for r in results if r["verdict"] == "unverified"]
    if uv:
        lines += ["## ❔ 未探测", "", "| 源 | 域名 | 说明 |", "|---|---|---|"]
        for r in uv:
            lines.append(f"| {r['name'][:44]} | {r['domain']} | {r['detail'][:70] or '有意跳过'} |")
        lines.append("")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    print(f"\nverdicts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"wrote {HEALTH.relative_to(ROOT)}")
    print(f"wrote {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
