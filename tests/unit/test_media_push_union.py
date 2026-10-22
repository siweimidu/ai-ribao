"""The media push must add files, never remove a sibling.

Measured on 2026-10-22. Three commits one minute apart:

    removed 19 files    <- this call only had its own 2 on disk
    added    2 files
    added   21 files    <- the 10-21 set came back, the 10-22 set did not

`reset --soft FETCH_HEAD` moved the index to the remote while the working tree held only the
files this call had written, so every other file looked deleted. Fifteen article images were
written, reported and URL-logged, then removed from the repository minutes later. The page
pointed at 404s.

`git checkout FETCH_HEAD -- .` materialises the remote tree instead: local files survive, remote
files arrive, and `git add -A` commits a union.
"""

from __future__ import annotations

import inspect

from aidaily import mediastore


def _code_only(source: str) -> str:
    """The function with comments and the docstring removed.

    Comments here explain why `reset --soft` was wrong; asserting on raw source would fail on the
    explanation itself.
    """
    body = source
    if '"""' in body:
        head, _, rest = body.partition('"""')
        _, _, tail = rest.partition('"""')
        body = head + tail
    return "\n".join(line.split("#")[0] for line in body.splitlines())


def test_push_materialises_the_remote_and_moves_head() -> None:
    """Two steps, both required.

    `checkout FETCH_HEAD -- .` brings the remote files onto disk. On its own it leaves HEAD
    behind, so the commit built on top is not a descendant of the remote tip and the push is
    rejected as non-fast-forward -- measured 2026-10-22, 38 images uploaded and 38 rejections.

    `reset --soft` alone moves HEAD but leaves the working tree holding only this call files,
    which is what deleted the siblings in the first place.

    Together: files arrive, HEAD advances, and the commit is a fast-forward.
    """
    code = _code_only(inspect.getsource(mediastore._push))
    assert "checkout" in code, "the remote tree must be checked out onto disk"
    assert "reset" in code and "--soft" in code, "HEAD must advance to the remote tip"
    # checkout must come first: reset --soft before checkout would keep the stale tree.
    assert code.index("checkout") < code.index("--soft")


def test_push_reports_what_git_sees() -> None:
    """A silent push that commits nothing is indistinguishable from one that worked."""
    source = inspect.getsource(mediastore._push)
    assert "磁盘" in source and "待提交" in source
    assert "推送成功" in source
    assert "推送失败" in source


def test_a_failed_push_returns_false_so_no_url_survives_its_file() -> None:
    source = inspect.getsource(mediastore.store_images)
    assert "if not _push(root, date):" in source
    assert "return {}" in source