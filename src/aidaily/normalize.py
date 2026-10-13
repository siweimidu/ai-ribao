"""Normalization: URL identity, title identity, content fingerprints.

The rules here decide what "the same thing" means, so they are deliberately
conservative and fully unit-tested. Two principles:

* Normalize the parts that are *provably* not content-bearing (tracking params,
  fragments, default ports, host case). Never normalize something that might carry
  meaning -- query params like `q`, `id`, `listId`, `key` select content, and URL
  paths are case-sensitive (GitHub usernames, repo names).
* Keep the original URL alongside the normalized one. Normalization is a dedup key,
  not a replacement: the digest must be able to show the URL the reader can use.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from collections import Counter
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# --- tracking parameters: dropped, because they never select content -------------
_TRACKING_EXACT = {
    "ref", "source", "fbclid", "gclid", "dclid", "msclkid", "yclid", "igshid",
    "mc_cid", "mc_eid", "spm", "from", "share_token", "share_source", "wt_mc",
    "cmpid", "campaign", "at_medium", "at_campaign", "__twitter_impression",
}
_TRACKING_PREFIXES = ("utm_", "pk_", "piwik_", "matomo_", "hsa_", "vero_", "oly_")

_DEFAULT_PORTS = {"http": 80, "https": 443}

_URL_IN_TITLE_RE = re.compile(r"https?://\S+", re.I)
_NOISE_PREFIXES = (
    "breaking:", "breaking ", "exclusive:", "update:", "just in:",
    "独家", "快讯", "重磅", "首发", "突发", "最新",
)
# Leading bracketed labels: 【重磅】标题 / [Exclusive] Title
_LEADING_TAG_RE = re.compile(r"^\s*[【\[（(][^】\]）)]{1,8}[】\]）)]\s*")
# Trailing " | Site Name" / " - Site Name" segments shorter than this are site brands.
# Deliberately small: a threshold of ~14 also swallows real titles that put the brand
# first ("机器之心 | OpenAI 发布新模型"), silently corrupting the dedup key.
_BRAND_SUFFIX_MAX = 8


def _is_tracking(name: str) -> bool:
    n = name.lower()
    return n in _TRACKING_EXACT or any(n.startswith(p) for p in _TRACKING_PREFIXES)


def normalize_url(url: str) -> str:
    """Return the canonical dedup key for a URL.

    Idempotent: normalize_url(normalize_url(u)) == normalize_url(u).
    Raises ValueError when the input is not an absolute http(s) URL -- callers that
    must tolerate junk should use `try_normalize_url`.
    """
    if not url or not isinstance(url, str):
        raise ValueError("empty url")

    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"unsupported scheme: {scheme!r}")
    if not parts.netloc:
        raise ValueError("missing host")

    host = parts.hostname or ""
    if not host:
        raise ValueError("missing host")
    host = host.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]

    # Credentials in a URL are a leak vector and never meaningful for identity.
    netloc = host
    port = parts.port
    if port and port != _DEFAULT_PORTS[scheme]:
        netloc = f"{host}:{port}"

    # Path is case-sensitive on purpose: /AI vs /ai can be different resources.
    path = parts.path or "/"
    while "//" in path:
        path = path.replace("//", "/")
    if len(path) > 1:
        path = path.rstrip("/") or "/"

    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)]
    kept.sort()
    query = urlencode(kept, doseq=True)

    # Scheme is unified to https: http:// and https:// for the same host+path are the
    # same publication in every source we audited.
    return urlunsplit(("https", netloc, path, query, ""))


def try_normalize_url(url: str) -> str | None:
    try:
        return normalize_url(url)
    except Exception:  # noqa: BLE001 - junk URLs must not crash a collect run
        return None


def url_domain(url: str) -> str:
    """Host without www., for grouping and the "same site" dedup rule."""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return ""
    return host[4:] if host.startswith("www.") else host


# --- titles ---------------------------------------------------------------------
def title_norm(title: str) -> str:
    """Aggressive but reversible-in-spirit title key: punctuation and case removed.

    Kept deliberately simple so a human can predict its output. It is a *key*, and
    is never shown to readers.
    """
    if not title:
        return ""
    t = unicodedata.normalize("NFKC", title)
    t = _URL_IN_TITLE_RE.sub(" ", t)
    t = t.lower()

    # Drop leading bracketed labels before anything else: 【重磅】标题 -> 标题
    while _LEADING_TAG_RE.match(t):
        t = _LEADING_TAG_RE.sub("", t, count=1)

    # Drop a short trailing brand segment: "标题 | 机器之心" -> "标题"
    for sep in ("|", "｜", " - ", " – ", " — "):
        if sep in t:
            head, _, tail = t.rpartition(sep)
            if head.strip() and len(tail.strip()) <= _BRAND_SUFFIX_MAX:
                t = head

    for p in _NOISE_PREFIXES:
        if t.startswith(p):
            t = t[len(p):]
            break

    # \W keeps unicode word chars (incl. CJK); drop underscores and separators too.
    return re.sub(r"[\W_]+", "", t, flags=re.UNICODE)


# --- content fingerprints -------------------------------------------------------
_WS_RE = re.compile(r"\s+")


def normalize_content(text: str) -> str:
    """Collapse formatting noise so that mirrored copies fingerprint identically."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = re.sub(r"<[^>]+>", " ", t)  # tolerate HTML bleed-through
    return _WS_RE.sub(" ", t).strip()


_BARE_URL_RE = re.compile(r"https?://\S+", re.I)
_TRAILING_JUNK_RE = re.compile(r"[\s·|>\-–—]+$")
# Lines that are pure feed furniture once their link is removed: "🔗 阅读原文",
# "via AIHOT ·", "Read more →". Leading symbols/emoji are stripped before matching.
_JUNK_LINE_RE = re.compile(
    r"^[\W_]*((read|learn)\s+more|阅读原文|原文链接|via\s+\S*|source:?)\s*[→»…\.]*$",
    re.I,
)


def strip_text_urls(text: str) -> str:
    """Remove bare URLs from display text.

    Feeds routinely embed their own links in the summary ("via AIHOT · https://...").
    Those links bypass the guarantee that every URL in the digest is one we recorded and
    verified, and they carry tracking parameters. The article's own link is already
    carried separately in `NormalizedItem.url`, so nothing is lost.
    """
    if not text:
        return ""
    out = _BARE_URL_RE.sub(" ", text)
    lines = []
    for line in out.split("\n"):
        cleaned = _TRAILING_JUNK_RE.sub("", line.strip())
        if cleaned and not _JUNK_LINE_RE.match(cleaned):
            lines.append(cleaned)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_TAG_RE = re.compile(r"</(p|div|li|h[1-6]|tr|br)\s*>|<br\s*/?>", re.I)


def strip_html(text: str, limit: int | None = None) -> str:
    """Turn a feed's HTML body into readable plain text.

    Needed because several feeds put markup in `summary`/`content` (Hacker News feeds
    ship `&lt;p&gt;Article URL: &lt;a href=...&gt;`), and rendering that verbatim buried
    the actual headline under tag soup. Block-level closers become newlines so the text
    does not run together.

    Deliberately **not** NFKC-normalised: NFKC rewrites full-width CJK punctuation to
    half-width (`：` becomes `:`), which is correct for a fingerprint but visibly wrong
    for text a reader sees. Normalisation lives in `normalize_content`, which is only
    used for hashing.
    """
    if not text:
        return ""
    t = _BLOCK_TAG_RE.sub("\n", text)
    t = _TAG_RE.sub("", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\u00a0]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = t.strip()
    return t[:limit] if limit else t


def content_fingerprint(text: str) -> str:
    return hashlib.sha256(normalize_content(text).encode("utf-8")).hexdigest()


# --- simhash --------------------------------------------------------------------
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def simhash_tokens(text: str) -> list[str]:
    """Tokenize for similarity: CJK uses character bigrams, latin uses words.

    Word tokens alone collapse to nothing on Chinese text; character bigrams give
    Chinese the same discriminative power that words give English.
    """
    t = normalize_content(text).lower()
    if not t:
        return []
    tokens: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            tokens.extend(buf)
            buf.clear()

    for ch in t:
        if _CJK_RE.match(ch):
            flush()
            tokens.append(ch)
        elif ch.isalnum():
            buf.append(ch)
        else:
            flush()
    flush()

    # CJK bigrams: consecutive CJK chars in the original token stream
    bigrams = [a + b for a, b in zip(tokens, tokens[1:]) if _CJK_RE.match(a) and _CJK_RE.match(b)]
    latin = [tok for tok in tokens if not _CJK_RE.match(tok)]
    return latin + bigrams


def simhash(text: str, bits: int = 64) -> int:
    """64-bit SimHash. Distance <= 3 means near-identical wording."""
    tokens = simhash_tokens(text)
    if not tokens:
        return 0
    weights = Counter(tokens)
    vector = [0] * bits
    for token, weight in weights.items():
        h = int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big")
        for i in range(bits):
            vector[i] += weight if (h >> i) & 1 else -weight
    out = 0
    for i in range(bits):
        if vector[i] > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def title_similarity(a: str, b: str) -> float:
    """Character-level ratio over normalized titles. 0.0-1.0."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    from difflib import SequenceMatcher

    # Short strings: exact-ish comparison is cheap. Long strings: the quadratic
    # matcher is fine at title lengths, so no shortcut is needed.
    return SequenceMatcher(None, a, b, autojunk=False).ratio()
