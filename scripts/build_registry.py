#!/usr/bin/env python3
"""Build sources/registry.yaml from the audit ledger.

The ledger (audit/sources_ledger.json) is the machine-readable result of the
static audit of the six repositories. This script freezes it into the registry
that the runtime reads, adding the fields the runtime needs (source_id, priority,
adapter, polling_interval, health_status).

Design rules enforced here:
  * every source keeps its FULL provenance (repo + file + config key) -- the
    coverage guard test asserts no provenance entry is ever lost;
  * nothing is deleted: sources that are disabled or unwired stay in the file
    with enabled: false;
  * source_id is deterministic, so re-running never churns the file.

Stdlib + PyYAML only.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "audit" / "sources_ledger.json"
OUT = ROOT / "sources" / "registry.yaml"

# category -> (priority, polling_interval). Lower priority number = more important.
CATEGORY_POLICY = {
    "lab-official": (1, "1h"),
    "zh-media": (2, "1h"),
    "media": (2, "1h"),
    "news": (2, "1h"),
    "lab-blog": (2, "2h"),
    "paper": (3, "6h"),
    "model": (3, "6h"),
    "dataset": (3, "12h"),
    "digest": (3, "2h"),
    "dev": (3, "6h"),
    "community": (3, "2h"),
    "product": (4, "6h"),
    "trend": (4, "24h"),
    "trend_keyword": (4, "24h"),
    "social": (4, "2h"),
    "search": (3, "1d"),
    "mixed": (3, "1h"),
    "preset": (5, "1d"),
    "example": (5, "1d"),
}
DEFAULT_POLICY = (3, "6h")

ADAPTER_BY_TYPE = {
    "rss": ("feedparser", "RssFetcher"),
    "atom": ("feedparser", "RssFetcher"),
    "jsonfeed": ("json", "JsonFeedFetcher"),
    "api": ("httpx_json", "ApiFetcher"),
    "scrape": ("bs4", "HtmlFetcher"),
}

# Sources whose URL embeds a credential placeholder, or which are documented as
# requiring a token/cookie. Kept explicit so the probe never reports a false "dead".
CREDENTIAL_ENV = {
    "https://api.follow.is": "FOLO_COOKIE",
    "https://api.producthunt.com/v2/api/graphql": "PRODUCT_HUNT_TOKEN",
    "https://api.tavily.com/search": "TAVILY_API_KEY",
    "https://lwn.net/headlines/full_text": "LWN_KEY",
}

# Endpoints that are NOT directly fetchable: a library talks to an internal API
# instead. Probing the public HTML page would report a misleading 429 "dead".
# These stay in the registry (never deleted) but are marked unverified.
LIBRARY_DRIVEN_HOSTS = {"trends.google.com"}

# Parameter-only rows: same endpoint, different query value. These are *parameters
# of one source*, not separate sources -- counting them separately inflates the
# source count. All of their provenance rows are preserved on the merged source.
# Google Trends appears twice in the audit: once as the fetcher itself (category
# "trend") and once as its 20 seed keywords (category "trend_keyword"). Both are the
# same endpoint, so both map to one group.
PARAMETER_GROUPS = {
    "trend_keyword": "google_trends",
    "trend": "google_trends",
}
GROUP_META = {
    "google_trends": ("Google Trends (pytrends, 20 个种子关键词)", "keywords", "trend_keyword"),
}


# Path segments that carry no identity: they are format/version/VCS boilerplate.
# `refs/heads/main` in particular appears in every raw.githubusercontent.com feed URL
# and would otherwise bloat the id to `...-com-main-anthropic-news`.
_GENERIC_SEGMENTS = {
    "feed", "feeds", "rss", "atom", "entries", "index", "compatible-mode",
    "v1", "v2", "v3", "api", "json", "xml", "default", "en", "zh", "all",
    "refs", "heads", "tags", "main", "master",
}


def slugify(url: str, name: str) -> str:
    """Deterministic, readable, order-independent slug: domain + up to 2 path segments.

    Two properties matter more than prettiness:

    * **Deterministic** -- the same URL must always yield the same id. `source_id`
      is referenced by sources/overrides.yaml and config `critical_sources`, so an
      id that changes when the registry is regenerated silently breaks overrides.
    * **Discriminating** -- one segment is not enough: all 12 Reddit sources end in
      `/top.json`, which collapsed them into `reddit-com-top`, `-2`, ... `-12`.
      Those numeric suffixes depend on iteration order and therefore drift.
    """
    p = urlparse(url)
    host = p.netloc.lower().replace("www.", "")
    base = re.sub(r"[^a-z0-9]+", "-", host).strip("-")

    parts: list[str] = []
    for seg in p.path.split("/"):
        if not seg:
            continue
        stem = re.sub(r"\.(xml|json|jsonl|html?|rss|atom)$", "", seg, flags=re.I)
        stem = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
        if stem and stem not in _GENERIC_SEGMENTS:
            parts.append(stem)

    tail = "-".join(parts[-2:])          # most specific two segments
    slug = f"{base}-{tail}" if tail else base
    if len(slug) > 64:
        slug = slug[:52].rstrip("-") + "-" + hashlib.sha1(url.encode()).hexdigest()[:8]
    return slug


def merge_parameter_rows(unique: list[dict]) -> tuple[list[dict], dict]:
    """Collapse parameter-only rows into their parent source, preserving provenance.

    A row whose only distinguishing feature is a query value (e.g. the 20 Google
    Trends seed keywords) is a *parameter of one source*, not a separate source.
    Counting them separately would inflate the registry; dropping them would lose
    information. So they are merged, and every row's provenance is carried onto
    the parent under `merged_provenance`.
    """
    out: list[dict] = []
    merged_stats: dict[str, int] = {}
    groups: dict[str, list[tuple[dict, str]]] = {}
    for entry in unique:
        cats = entry.get("categories") or []
        grp = next((PARAMETER_GROUPS[c] for c in cats if c in PARAMETER_GROUPS), None)
        if grp:
            groups.setdefault(grp, []).append((entry, next(c for c in cats if c in PARAMETER_GROUPS)))
        else:
            out.append(entry)

    for gid, tagged in groups.items():
        name, param_field, param_category = GROUP_META[gid]
        rows = [e for e, _ in tagged]
        param_rows = [e for e, c in tagged if c == param_category]
        param_rows.sort(key=lambda r: r["normalized_url"])
        params = []
        for r in param_rows:
            label = r["name"].split(":", 1)[-1].strip() if ":" in r["name"] else r["name"]
            params.append({"value": label, "url": r["normalized_url"], "name": r["name"]})
        # the merged source is anchored on the fetcher row when present
        parent = next((e for e, c in tagged if c != param_category), rows[0])
        base = dict(parent)
        base["name"] = name
        base["type"] = "api"
        base["categories"] = sorted({c for r in rows for c in (r.get("categories") or [])}) or ["trend"]
        base["languages"] = ["en"]
        base["found_in"] = [fi for r in rows for fi in r["found_in"]]
        base["notes"] = [
            f"由 {len(rows)} 条记录（1 个 fetcher + {len(param_rows)} 个种子关键词）合并；"
            f"{param_field} 见 params 字段（pytrends 驱动，公开 HTML 页不可直接抓取）"
        ]
        base["params"] = {param_field: params}
        base["merged_parameter_rows"] = len(rows)
        out.append(base)
        merged_stats[gid] = len(rows)

    out.sort(key=lambda r: r["normalized_url"])
    return out, merged_stats


def load_local_sources() -> list[dict]:
    """Sources that are not from the six audited repositories.

    `registry.yaml` is generated from `audit/sources_ledger.json`, and that ledger only
    covers the six repositories this project started from. Anything added later -- a source
    discovered by testing, or supplied by the user -- has no place in it, and editing
    `registry.yaml` by hand loses the change on the next rebuild.

    So local additions live in `sources/local.yaml` and are appended here. They are real
    registry entries: same adapters, same dedup rules, same never-delete policy. The only
    difference is provenance -- an audited source's parameters are evidence and cannot be
    rewritten, while a local source is defined directly.

    Every entry must carry `why` and `found_in`. A source without a stated reason is a
    source nobody can later evaluate, and `found_in` is what makes it traceable at all.
    """
    path = ROOT / "sources" / "local.yaml"
    if not path.exists():
        return []
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = doc.get("sources") or []
    out: list[dict] = []
    for row in rows:
        for required in ("source_id", "name", "url", "why", "found_in"):
            if not row.get(required):
                raise SystemExit(f"sources/local.yaml: {row.get('source_id') or row} 缺少 {required}")
        parsed = urlparse(row["url"])
        source_type = row.get("source_type", "rss")
        fetch_method, adapter = ADAPTER_BY_TYPE.get(source_type, ("feedparser", "RssFetcher"))
        out.append({
            "source_id": row["source_id"],
            "name": row["name"],
            "url": row["url"],
            "normalized_url": row["url"],
            "domain": parsed.netloc,
            "category": row.get("category", "mixed"),
            "categories_all": [row.get("category", "mixed")],
            "language": row.get("language", "zh"),
            "source_type": source_type,
            "fetch_method": row.get("fetch_method", fetch_method),
            "adapter": row.get("adapter", adapter),
            "enabled": bool(row.get("enabled", True)),
            "priority": int(row.get("priority", 3)),
            "polling_interval": row.get("polling_interval", "6h"),
            "timeout_s": int(row.get("timeout_s", 20)),
            "needs_credential": row.get("needs_credential"),
            "dedup_group": row.get("dedup_group"),
            "health_status": "unverified",
            "last_success_at": None,
            "last_failure_at": None,
            "notes": (row.get("notes") or "").strip() or None,
            "why": (row.get("why") or "").strip(),
            "license_note": (row.get("license_note") or "").strip() or None,
            "found_in": row["found_in"],
            "provenance_count": len(row["found_in"]),
            "repositories": row.get("repositories") or [],
            "params": None,
            "merged_parameter_rows": 1,
            "added_locally": True,
        })
    return out


def main() -> int:
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    unique = ledger["unique_sources"]
    raw_url_rows = len(unique)
    unique, merged_stats = merge_parameter_rows(unique)

    used: dict[str, int] = {}
    sources = []
    for entry in unique:
        url = entry["normalized_url"]
        cat = (entry.get("categories") or ["mixed"])[0]
        stype = entry["type"]
        priority, interval = CATEGORY_POLICY.get(cat, DEFAULT_POLICY)
        fetch_method, adapter = ADAPTER_BY_TYPE.get(stype, ("httpx_json", "ApiFetcher"))

        slug = slugify(url, entry["name"])
        if slug in used:
            # Deterministic disambiguation by content hash. Never a sequence number:
            # `-2`, `-3` would shift whenever the source list is reordered, breaking
            # every override and critical_sources reference that points at them.
            slug = f"{slug}-{hashlib.sha1(url.encode()).hexdigest()[:6]}"
        used[slug] = 1
        source_id = f"{stype}:{slug}"

        parsed = urlparse(url)
        base_host_url = f"{parsed.scheme}://{parsed.netloc}"
        cred = CREDENTIAL_ENV.get(base_host_url) or CREDENTIAL_ENV.get(url)
        if not cred and "${" in url:
            cred = "REQUIRED_ENV_VAR"

        host = parsed.netloc.lower().replace("www.", "")
        if cred:
            health = "needs_credential"
        elif not entry.get("enabled", True):
            health = "disabled"
        elif host in LIBRARY_DRIVEN_HOSTS:
            # Not probeable: a library talks to an internal API, not to this URL.
            health = "unverified"
        else:
            health = "unverified"

        sources.append(
            {
                "source_id": source_id,
                "name": entry["name"],
                "url": url,
                "normalized_url": url,
                "domain": parsed.netloc.lower().replace("www.", ""),
                "category": cat,
                "categories_all": entry.get("categories") or [],
                "language": (entry.get("languages") or [None])[0],
                "source_type": stype,
                "fetch_method": fetch_method,
                "adapter": adapter,
                "enabled": bool(entry.get("enabled", True)) and not cred,
                "priority": priority,
                "polling_interval": interval,
                "timeout_s": 20,
                "needs_credential": cred,
                "dedup_group": None,
                "health_status": health,
                "last_success_at": None,
                "last_failure_at": None,
                "notes": "; ".join(entry.get("notes") or []) or None,
                # ---- provenance (never trimmed) ----
                "found_in": entry["found_in"],
                "provenance_count": len(entry["found_in"]),
                "repositories": sorted({fi.split(":")[0] for fi in entry["found_in"]}),
                "params": entry.get("params"),
                "merged_parameter_rows": entry.get("merged_parameter_rows", 1),
            }
        )

    local = load_local_sources()
    existing = {s["source_id"] for s in sources}
    for row in local:
        if row["source_id"] in existing:
            # A local entry may not shadow an audited one: the audited parameters came from
            # evidence, and silently replacing them would break the provenance chain the
            # coverage guard asserts.
            raise SystemExit(
                f"sources/local.yaml: {row['source_id']} 与审计源同名；"
                "增补源必须用新的 source_id"
            )
        sources.append(row)

    sources.sort(key=lambda s: (s["priority"], s["category"], s["source_id"]))

    provenance_rows = sum(s["provenance_count"] for s in sources)
    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "scripts/build_registry.py",
        "source_of_truth": "audit/sources_ledger.json (static audit of six repositories)",
        "policy": {
            "never_delete": "Sources are never removed; disable via sources/overrides.yaml instead.",
            "coverage_guard": "tests/contract/test_source_coverage.py asserts every provenance entry survives.",
        },
        "stats": {
            "url_level_rows_before_merge": raw_url_rows,
            "parameter_rows_merged": raw_url_rows - len(sources),
            "merge_breakdown": merged_stats,
            "unique_sources": len(sources),
            "provenance_rows": provenance_rows,
            "by_repository": {
                r: sum(1 for s in sources if r in s["repositories"])
                for r in sorted({r for s in sources for r in s["repositories"]})
            },
            "by_source_type": {
                t: sum(1 for s in sources if s["source_type"] == t)
                for t in sorted({s["source_type"] for s in sources})
            },
            "by_category": {
                c: sum(1 for s in sources if s["category"] == c)
                for c in sorted({s["category"] for s in sources})
            },
        },
        "sources": sources,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")

    print(f"wrote {OUT.relative_to(ROOT)}")
    print(f"  URL-level rows (from ledger): {raw_url_rows}")
    print(f"  parameter rows merged      : {raw_url_rows - len(sources)}  {merged_stats}")
    print(f"  unique sources (endpoints) : {len(sources)}")
    print(f"  provenance rows (preserved): {provenance_rows}")
    print(f"  enabled for probe          : {sum(1 for s in sources if s['enabled'])}")
    print(f"  needs credential           : {sum(1 for s in sources if s['health_status'] == 'needs_credential')}")
    print(f"  disabled/unwired           : {sum(1 for s in sources if s['health_status'] == 'disabled')}")
    print("  by repository              : " + ", ".join(f"{k}={v}" for k, v in doc["stats"]["by_repository"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
