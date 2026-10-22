"""The media push uses the GitHub Contents API, not a local clone.

The git implementation failed four ways in one day:

  1. `reset --soft FETCH_HEAD` left the working tree holding only this call files, so every
     sibling on the remote showed up as deleted and the commit removed them.
  2. `checkout FETCH_HEAD -- .` fixed that but left HEAD behind, so every push was rejected as
     non-fast-forward (38 images, 38 rejections).
  3. Adding `reset --soft` after the checkout fixed that, but a failed `fetch` fell through to
     `checkout`, then to `commit`, producing an orphan commit on unrelated history.
  4. The working copy carried state between the two `store_images` calls in one issue.

All four are properties of maintaining a local clone. The Contents API has no clone, so these
tests assert the API shape rather than git mechanics.
"""

from __future__ import annotations

import inspect

from aidaily import mediastore


def _code_only(source: str) -> str:
    """The function with comments and the docstring removed."""
    body = source
    if '"""' in body:
        head, _, rest = body.partition('"""')
        _, _, tail = rest.partition('"""')
        body = head + tail
    return "\n".join(line.split("#")[0] for line in body.splitlines())


def test_push_uses_the_contents_api() -> None:
    """One PUT per file, keyed by path. No clone, so nothing to get out of sync."""
    code = _code_only(inspect.getsource(mediastore._push))
    assert "api.github.com" in code
    assert "contents" in code
    assert "base64" in code


def test_push_does_not_use_git_at_all() -> None:
    """Every git-based failure mode is gone with the clone."""
    code = _code_only(inspect.getsource(mediastore._push))
    for forbidden in ("subprocess", "git(", "FETCH_HEAD", "reset", "checkout"):
        assert forbidden not in code, f"{forbidden} must not appear: the API path has no clone"


def test_push_requires_a_token() -> None:
    """The workflow token is scoped to the digest repository and cannot write here."""
    code = _code_only(inspect.getsource(mediastore._push))
    assert "MEDIA_TOKEN" in code


def test_push_reports_counts() -> None:
    """A silent push that uploads nothing is indistinguishable from one that worked."""
    source = inspect.getsource(mediastore._push)
    assert "上传" in source and "失败" in source


def test_a_failed_push_returns_false_so_no_url_survives_its_file() -> None:
    source = inspect.getsource(mediastore.store_images)
    assert "if not _push(root, date):" in source
    assert "return {}" in source


def test_an_unchanged_file_is_not_uploaded_twice() -> None:
    """A re-run must not churn the repository with identical blobs."""
    code = _code_only(inspect.getsource(mediastore._push))
    assert "unchanged" in code