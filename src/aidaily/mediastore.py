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
    images: dict[str, bytes],
    *,
    date: str,
    workdir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, str]:
    """Write images into the media repository and return event_id to public URL.

    A failure to push returns an empty mapping rather than raising: pictures are decoration, and
    a repository that will not accept a push must cost the pictures, not the issue.
    """
    from .media import content_hash

    root = workdir or DEFAULT_WORKDIR
    date_dir = root / date
    date_dir.mkdir(parents=True, exist_ok=True)

    repo = repo_for(date)
    urls: dict[str, str] = {}
    written = 0
    for event_id, data in images.items():
        if not data:
            continue
        filename = f"{event_id}-{content_hash(data)}.webp"
        path = date_dir / filename
        if not path.exists():
            path.write_bytes(data)
            written += 1
        urls[event_id] = public_url(repo, date, filename)

    if dry_run or written == 0:
        return urls

    if not _push(root, date):
        return {}
    return urls


def _push(root: Path, date: str) -> bool:
    """Commit and push the day directory. True when the remote accepted it."""
    token = os.environ.get("MEDIA_TOKEN", "").strip()
    repo = repo_for(date)

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=str(root), capture_output=True, text=True, encoding="utf-8"
        )

    try:
        if not (root / ".git").exists():
            if token:
                url = f"https://x-access-token:{token}@github.com/{repo}.git"
            else:
                url = f"https://github.com/{repo}.git"
            if git("clone", "--depth", "1", "--branch", MEDIA_BRANCH, url, ".").returncode != 0:
                return False
        git("add", "-A")
        if not git("status", "--porcelain").stdout.strip():
            return True
        if git(
            "-c", "user.name=ai-daily", "-c", "user.email=ai-daily@local",
            "commit", "-q", "-m", f"media: {date}",
        ).returncode != 0:
            return False
        if token:
            git("remote", "set-url", "origin",
                f"https://x-access-token:{token}@github.com/{repo}.git")
        return git("push", "-q", "origin", MEDIA_BRANCH).returncode == 0
    except Exception:
        return False


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
