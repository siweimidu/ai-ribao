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


def test_push_materialises_the_remote_instead_of_soft_resetting() -> None:
    """The property that stops sibling files from being deleted."""
    code = _code_only(inspect.getsource(mediastore._push))
    assert "checkout" in code, "the remote tree must be checked out onto disk"
    assert "--soft" not in code, "reset --soft is what produced the deletions"


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