"""Where downloaded images live, and how the page references them.

## The storage decision, with the numbers that drove it

Images are re-encoded to 1200px WebP before storage: measured 226,458 bytes to 23,590 bytes,
10.4% of the original. At roughly 25 KB per image and 40 images a day that is about 1 MB a day,
356 MB a year.

A GitHub repository has a soft limit around 1 GB, so a single media repository holds about three
years. That is why MEDIA_REPOS exists: when it fills, add a row, and images dated after that row
go to the new repository. Old pages keep working because every image URL is absolute and carries
the repository that holds it.

## Why not store in the main repository

The main repository is 3 MB of code plus the digest JSON. Mixing 356 MB a year of binaries into
it would slow every clone and every CI checkout for files nothing in the code needs.

## Why jsDelivr rather than raw.githubusercontent

Measured 2026-10-21: jsDelivr serves from Cloudflare with cache-control public, max-age=604800
and a correct image/webp content type; raw.githubusercontent sends no cache headers at all.

## Why git push rather than an upload API

There is no free object-storage API here, and a repository is the one store this project already
owns. git also gives idempotence for free: re-storing the same bytes produces the same path and
the same content hash, so a re-run adds nothing.
"""

from __future__ import annotations

import sys
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

#: (effective_from, repository), newest last. An image dated on or after a row goes to that
#: repository. Adding a row is all it takes to roll over to a fresh store.
MEDIA_REPOS: tuple[tuple[str, str], ...] = (
    ("2026-01-01", "siweimidu/ai-daily-media"),
)

#: The branch jsDelivr reads. Named, not HEAD, because the CDN URL has to be stable.
MEDIA_BRANCH = "main"

#: Where the local working copy of the media repository is kept between runs.
DEFAULT_WORKDIR = Path("data") / "media-repo"


def repo_for(date: str) -> str:
    """The media repository that owns an image published on the given date."""
    chosen = MEDIA_REPOS[0][1]
    for effective_from, repo in MEDIA_REPOS:
        if date >= effective_from:
            chosen = repo
    return chosen


def public_url(repo: str, date: str, filename: str) -> str:
    """The absolute URL an archived image is served from.

    Absolute on purpose: an issue published today keeps rendering correctly after a rollover,
    because it names the repository that holds it rather than the current one.
    """
    return f"https://cdn.jsdelivr.net/gh/{repo}@{MEDIA_BRANCH}/{date}/{filename}"


def store_images(
    images: dict[str, list[bytes]],
    *,
    date: str,
    workdir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, list[str]]:
    """Write images into the media repository and return event_id to public URL.

    A failure to push returns an empty mapping rather than raising: pictures are decoration, and
    a repository that will not accept a push must cost the pictures, not the issue.
    """
    from .media import content_hash

    root = workdir or DEFAULT_WORKDIR
    date_dir = root / date
    date_dir.mkdir(parents=True, exist_ok=True)

    repo = repo_for(date)
    urls: dict[str, list[str]] = {}
    for event_id, group in images.items():
        if not group:
            continue
        # `m001`, `m002` ... mirrors how the reference site names its image rows, and keeps
        # the reading order stable when a story has several pictures.
        for index, data in enumerate(group, 1):
            if not data:
                continue
            filename = f"{event_id}-m{index:03d}-{content_hash(data)}.webp"
            path = date_dir / filename
            if not path.exists():
                path.write_bytes(data)
            urls.setdefault(event_id, []).append(public_url(repo, date, filename))

    if dry_run:
        return urls

    # Push even when nothing was written: a previous run may have stored the files and failed to
    # push them, and a re-run must repair that rather than report success with pictures that
    # exist only on local disk.
    if not _push(root, date):
        return {}
    return urls


def _push(root: Path, date: str) -> bool:
    """Upload the day directory through the GitHub Contents API. True when every file landed.

    ## Why the API and not git

    The git implementation was replaced after it failed four different ways in one day:

      1. `reset --soft FETCH_HEAD` left the working tree holding only this call files, so every
         sibling on the remote showed up as deleted and the commit removed them.
      2. `checkout FETCH_HEAD -- .` fixed the deletions but left HEAD behind, so every push was
         rejected as non-fast-forward (38 images, 38 rejections).
      3. Adding `reset --soft` after the checkout fixed that, but a failed `fetch` fell through
         to `checkout`, then to `commit`, producing an orphan commit on unrelated history.
      4. Even when all of that lined up, the working copy carried state between the two
         `store_images` calls in one issue (article pictures, then repository cards), and the
         second call could still re-point the tree.

    Every one of those is a property of *maintaining a local clone*. The Contents API has no
    clone: each file is a PUT against a path, keyed by the current blob sha. There is no index,
    no HEAD, no fast-forward, and no shared state between calls. Uploading the same bytes twice
    is a no-op; uploading after someone else changed the branch still applies.

    Cost is one request per file instead of one per batch, which at a few dozen images a day is
    well inside the 5000/hour authenticated quota. `MEDIA_TOKEN` is required: the workflow
    `GITHUB_TOKEN` is scoped to the digest repository and cannot write here.
    """
    import base64
    import json as _json
    import urllib.error
    import urllib.request

    token = os.environ.get("MEDIA_TOKEN", "").strip()
    if not token:
        print("配图上传：缺少 MEDIA_TOKEN，跳过上传", file=sys.stderr)
        return False

    repo = repo_for(date)
    day_dir = root / date
    if not day_dir.exists():
        print(f"配图上传：{day_dir} 不存在", file=sys.stderr)
        return False

    files = sorted(p for p in day_dir.glob("*") if p.is_file())
    if not files:
        print(f"配图上传：{day_dir} 是空的", file=sys.stderr)
        return False

    api = f"https://api.github.com/repos/{repo}/contents"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "ai-daily",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    def call(method: str, url: str, payload: dict | None = None) -> tuple[int, dict]:
        body = _json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, _json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                detail = _json.loads(raw or b"{}")
            except ValueError:
                detail = {"message": raw[:120].decode("utf-8", "replace")}
            return exc.code, detail
        except Exception as exc:  # noqa: BLE001
            return 0, {"message": f"{type(exc).__name__}: {exc}"}

    uploaded = 0
    unchanged = 0
    failed: list[str] = []

    for path in files:
        target = f"{api}/{date}/{path.name}"

        # Does it already exist with the same bytes? A re-run must not churn the repository.
        status, existing = call("GET", target)
        sha = existing.get("sha") if status == 200 else None

        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        if sha:
            status, current = call("GET", f"{api}/{date}/{path.name}")
            if status == 200 and current.get("content"):
                on_remote = base64.b64decode(current["content"])
                if on_remote == path.read_bytes():
                    unchanged += 1
                    continue

        payload = {
            "message": f"media: {date}/{path.name}",
            "content": encoded,
            "branch": MEDIA_BRANCH,
        }
        if sha:
            payload["sha"] = sha

        status, result = call("PUT", target, payload)
        if status in (200, 201):
            uploaded += 1
        else:
            failed.append(f"{path.name}: {status} {str(result.get('message'))[:80]}")

    print(
        f"配图上传：{len(files)} 个文件，上传 {uploaded}，已存在 {unchanged}，失败 {len(failed)}",
        file=sys.stderr,
    )
    for line in failed[:5]:
        print(f"  ✗ {line}", file=sys.stderr)

    return not failed

def prune(keep_days: int = 90, *, workdir: Path | None = None, dry_run: bool = False) -> list[str]:
    """Delete day directories older than keep_days. Returns what would be (or was) removed.

    Images older than this are still referenced by the pages that published them, so deleting the
    files breaks those pages. The default is deliberately generous; the digest JSON keeps the
    record forever.
    """
    root = workdir or DEFAULT_WORKDIR
    if not root.exists():
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    removed: list[str] = []
    for day in sorted(root.iterdir()):
        if not day.is_dir() or not day.name.startswith("20"):
            continue
        if day.name >= cutoff:
            continue
        removed.append(day.name)
        if not dry_run:
            shutil.rmtree(day, ignore_errors=True)
    return removed
