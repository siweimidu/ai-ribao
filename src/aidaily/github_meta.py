"""Repository metadata for GitHub-hosted stories, cached on disk.

## Why a cache is not optional

The unauthenticated REST quota is 60 requests an hour. One issue can carry a dozen GitHub stories,
three issues a day, and each story needs three requests (repo, languages, contributors) plus one
GraphQL call for discussions. Without a cache the first run of the day would exhaust the quota and
the rest of the day would silently lose every card.

With a token the quota is 5000/h, which is enough -- but a cache still matters, because the data
changes slowly and re-fetching a repository every three hours is waste.

## Cache shape

`data/state/github_cache.json`: `{"owner/repo": {"fetched_at": iso, "data": {...}}}`. An entry is
fresh for `TTL_HOURS`; stars move, but not fast enough to matter inside a day.

## What cannot be fetched

`Used by` does not exist in the API. GitHub own card shows it because the number comes from the
internal dependency graph; `usedBy` is not a GraphQL field and the REST dependents endpoint
returns 404 to ordinary tokens. The card omits it rather than inventing a figure.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

CACHE = Path("data") / "state" / "github_cache.json"
TTL_HOURS = 20

#: Recognises a repository URL and keeps owner/repo. Trailing paths (`/tree/main/...`), issues and
#: pull requests are dropped: they describe a place inside the repository, not another repository.
_REPO_URL = re.compile(r"^https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(?:[/?#]|$)")

#: Owner names that are not users or organisations but GitHub own sections. A link to
#: `github.com/features/copilot` is not a repository.
_NOT_OWNERS = frozenset({
    "features", "topics", "collections", "sponsors", "marketplace", "pricing", "enterprise",
    "about", "site", "security", "readme", "explore", "trending", "events", "login", "join",
    "settings", "notifications", "new", "organizations", "users", "apps", "contact", "customer-stories",
})


def repo_of(url: str) -> str | None:
    """`owner/repo` for a GitHub repository URL, else None."""
    match = _REPO_URL.match(url or "")
    if not match:
        return None
    owner, name = match.group(1), match.group(2)
    if owner.lower() in _NOT_OWNERS:
        return None
    if name.endswith(".git"):
        name = name[:-4]
    return f"{owner}/{name}"


def _token() -> str:
    return os.environ.get("GITHUB_TOKEN", "").strip()


def _headers() -> dict[str, str]:
    headers = {"User-Agent": "ai-daily", "Accept": "application/vnd.github+json"}
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def _fresh(entry: dict, now: datetime) -> bool:
    try:
        when = datetime.fromisoformat(str(entry.get("fetched_at")))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return now - when < timedelta(hours=TTL_HOURS)


async def _contributors(client: httpx.AsyncClient, repo: str) -> int | None:
    """Contributor count, read from the Link header instead of counting rows.

    `per_page=1` plus `Link: <...?page=3824>; rel="last"` gives the total in one small response;
    paginating through thousands of contributors would cost a hundred requests.
    """
    try:
        response = await client.get(
            f"https://api.github.com/repos/{repo}/contributors",
            params={"per_page": 1, "anon": "true"},
            headers=_headers(),
        )
        if response.status_code != 200:
            return None
        match = re.search(r'[?&]page=(\d+)>; rel="last"', response.headers.get("Link", ""))
        return int(match.group(1)) if match else None
    except Exception:
        return None


async def _discussions(repo: str) -> int | None:
    """Discussion count. REST has no endpoint for it, so this shells out to `gh api graphql`."""
    owner, _, name = repo.partition("/")
    query = (
        'query { repository(owner: "%s", name: "%s") { discussions { totalCount } } }'
        % (owner, name)
    )
    try:
        result = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={query}"],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        payload = json.loads(result.stdout or "{}")
        repo_node = (payload.get("data") or {}).get("repository") or {}
        return ((repo_node.get("discussions") or {}).get("totalCount"))
    except Exception:
        return None


async def fetch(client: httpx.AsyncClient, repo: str) -> dict | None:
    """Everything the card needs for one repository, or None when the API refuses."""
    try:
        base = await client.get(f"https://api.github.com/repos/{repo}", headers=_headers())
        if base.status_code != 200:
            return None
        data = base.json()
    except Exception:
        return None

    languages: dict[str, float] = {}
    try:
        raw = await client.get(f"https://api.github.com/repos/{repo}/languages", headers=_headers())
        if raw.status_code == 200:
            counts = raw.json()
            total = sum(counts.values()) or 1
            ordered = sorted(counts.items(), key=lambda kv: -kv[1])
            languages = {name: 100.0 * value / total for name, value in ordered[:6]}
    except Exception:
        pass

    return {
        "full_name": data.get("full_name") or repo,
        "description": data.get("description") or "",
        "stars": int(data.get("stargazers_count") or 0),
        "forks": int(data.get("forks_count") or 0),
        "language": data.get("language") or "",
        "license": ((data.get("license") or {}).get("spdx_id") or ""),
        "topics": list(data.get("topics") or [])[:6],
        "created": str(data.get("created_at") or "")[:10],
        "pushed": str(data.get("pushed_at") or "")[:10],
        "contributors": await _contributors(client, repo),
        "discussions": await _discussions(repo),
        "languages": languages,
    }


async def fetch_many(repos: list[str], *, cache_path: Path | None = None) -> dict[str, dict]:
    """Metadata for many repositories, served from cache where fresh. Never raises."""
    path = cache_path or CACHE
    store = _load(path)
    now = datetime.now(timezone.utc)
    out: dict[str, dict] = {}
    missing: list[str] = []

    for repo in repos:
        entry = store.get(repo)
        if entry and _fresh(entry, now):
            out[repo] = entry["data"]
        else:
            missing.append(repo)

    if missing:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
            for repo in missing:
                data = await fetch(client, repo)
                if data is None:
                    continue
                out[repo] = data
                store[repo] = {"fetched_at": now.isoformat(), "data": data}
        if store:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")

    return out