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
    """Commit and push the day directory. True when the remote accepted it.

    ## What this used to do, and why it lost images

    `reset --soft FETCH_HEAD` made the index match the remote while leaving the working tree
    exactly as it was on disk. Since the working tree here holds *only the files this call
    wrote*, every other file on the remote showed up as deleted. The commit that followed
    therefore removed its siblings.

    Measured on 2026-10-22, three consecutive commits one minute apart:

        removed 19 files    <- this call only had its own 2
        added    2 files
        added   21 files    <- the 10-21 set came back, the 10-22 set did not

    Fifteen article images were written, reported, URL-logged and never survived. The page
    pointed at files that had been deleted from the repository minutes after they landed.

    ## What it does now

    `git checkout FETCH_HEAD -- .` **populates** the working tree from the remote instead of
    merely re-pointing the index. Everything the remote has is present on disk, this call
    adds its own files on top, and `git add -A` therefore commits a union rather than a
    replacement. Deletions cannot happen because nothing is missing.

    Same cost as before (`--depth 1`), and the working copy stays useful between calls.
    """
    token = os.environ.get("MEDIA_TOKEN", "").strip()
    repo = repo_for(date)

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=str(root), capture_output=True, text=True, encoding="utf-8"
        )

    def remote_url() -> str:
        if token:
            return f"https://x-access-token:{token}@github.com/{repo}.git"
        return f"https://github.com/{repo}.git"

    try:
        root.mkdir(parents=True, exist_ok=True)
        if not (root / ".git").exists():
            if git("init", "-q", "-b", MEDIA_BRANCH).returncode != 0:
                return False
            if git("remote", "add", "origin", remote_url()).returncode != 0:
                return False
        elif token:
            git("remote", "set-url", "origin", remote_url())

        # Fetch on every push: `store_images` runs twice per issue (article pictures, then
        # repository cards) and each call pushes.
        fetched = git("fetch", "-q", "--depth", "1", "origin", MEDIA_BRANCH)
        if fetched.returncode != 0:
            # **A failed fetch must not fall through to a commit.**
            #
            # Measured while debugging 2026-10-22: when `fetch` failed on a network timeout,
            # execution continued, `checkout FETCH_HEAD` failed too ("invalid reference"), and the
            # function still staged the local files and committed them on top of an unrelated
            # history. The push then failed as non-fast-forward and the images were lost, with
            # only a one-line rc=128 in the log.
            #
            # One retry first, because a transient failure is worth it.
            for _ in range(2):
                fetched = git("fetch", "-q", "--depth", "1", "origin", MEDIA_BRANCH)
                if fetched.returncode == 0:
                    break
            if fetched.returncode != 0:
                print(
                    f"配图上传：fetch 失败 rc={fetched.returncode} {(fetched.stderr or '')[:120]}",
                    file=sys.stderr,
                )
                return False

        if fetched.returncode == 0:
            # **Materialise the remote tree.** `reset --soft` only moved the index; checkout
            # brings the files onto disk so nothing looks deleted.
            # **Move HEAD as well as the files.**
            #
            # `checkout FETCH_HEAD -- .` brings the remote tree onto disk but leaves HEAD where it
            # was, so the commit built on top is not a descendant of the remote tip and the push
            # is rejected as non-fast-forward. Measured 2026-10-22: 38 images uploaded, 38
            # failures, every one `! [rejected] HEAD -> main (non-fast-forward)`.
            #
            # `reset --soft` moves HEAD without touching the working tree, which after the
            # checkout above already holds the union. Doing both is what makes the commit a
            # fast-forward of the remote.
            checkout = git("checkout", "-q", "-f", "FETCH_HEAD", "--", ".")
            if checkout.returncode != 0:
                print(
                    f"配图上传：checkout 失败 rc={checkout.returncode} {(checkout.stderr or '')[:120]}",
                    file=sys.stderr,
                )
                return False
            reset = git("reset", "-q", "--soft", "FETCH_HEAD")
            if reset.returncode != 0:
                print(
                    f"配图上传：reset 失败 rc={reset.returncode} {(reset.stderr or '')[:120]}",
                    file=sys.stderr,
                )
                return False
        else:
            # Empty remote: the first push. Nothing to materialise.
            pass

        staged = git("add", "-A")
        status = git("status", "--porcelain").stdout.strip()
        on_disk = len(list((root / date).glob("*")))
        print(
            f"配图上传：磁盘 {on_disk} 个文件，git 待提交 {len(status.splitlines()) if status else 0} 项",
            file=sys.stderr,
        )
        if staged.returncode != 0:
            print(f"配图上传：git add 失败 rc={staged.returncode}", file=sys.stderr)
            return False
        if not status:
            print(f"配图上传：无差异，无需提交（磁盘 {on_disk} 个文件）", file=sys.stderr)
            return True

        if git(
            "-c", "user.name=ai-daily", "-c", "user.email=ai-daily@local",
            "commit", "-q", "-m", f"media: {date}",
        ).returncode != 0:
            return False

        for attempt in range(2):
            pushed = git("push", "-q", "origin", f"HEAD:{MEDIA_BRANCH}")
            if pushed.returncode == 0:
                print("配图上传：推送成功", file=sys.stderr)
                return True
            print(
                f"配图上传：推送失败 rc={pushed.returncode} {(pushed.stderr or '')[:120]}",
                file=sys.stderr,
            )
            if attempt == 0:
                if git("fetch", "-q", "--depth", "1", "origin", MEDIA_BRANCH).returncode != 0:
                    return False
                git("checkout", "-q", "-f", "FETCH_HEAD", "--", ".")
                git("reset", "-q", "--soft", "FETCH_HEAD")
                git("add", "-A")
                git(
                    "-c", "user.name=ai-daily", "-c", "user.email=ai-daily@local",
                    "commit", "-q", "-m", f"media: {date}",
                )
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"配图上传：异常 {type(exc).__name__}: {exc}"[:160], file=sys.stderr)
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
