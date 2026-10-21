"""Article images: where they come from, and why they are fetched rather than generated.

## The mechanism, taken apart first

The reference site this project measures itself against shows a picture on most entries, and the
assumption that it *draws* them is wrong. Every image on its 2026-10-21 issue traces back to the
publisher: an X post attachment, a GitHub repository social preview, a screenshot in the official
help centre. Nothing is generated and nothing is stock illustration.

That matters because it means the capability is a *fetch* pipeline, not an image model. Four
sources, in order of yield:

* **og:image** -- most publishers declare a social card. One GET, one regex.
* **twitter:image** -- falls back when a site only fills the Twitter card.
* **the page own img tags** -- first candidate, icons excluded.
* **api.fxtwitter.com** -- for X, whose pages are a JavaScript shell with no usable card.

## Measured yield

On the 2026-10-21 archive, first attempt per entry: **5 of 6 succeeded**, 12-31 KB each after
WebP. The one failure was an aggregator page that server-renders no image metadata at all.

## Why the URL is normalised rather than stored raw

og:image is frequently relative, protocol-relative, or carrying a resize query
(`?width=600&fit=crop`). Storing it raw gives a broken img on the page. `_absolute` resolves it
against the article URL; `_drop_resize` strips the CDN resize parameters so the archived copy is
the full-size image rather than a thumbnail.

## Why every failure is silent

An image is decoration. A run must never die because one publisher returns 403 -- and several do
(measured: openai.com returns 403 to a non-browser agent). Every fetch returns None and the entry
renders without a picture.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

#: Served to publishers that reject the default python-httpx agent.
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

#: og:image in either attribute order. Both layouts are common.
_OG_IMAGE = (
    re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I),
)
_TW_IMAGE = (
    re.compile(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']', re.I),
)
_IMG_TAG = re.compile(r'<img[^>]+src=["\']([^"\']+)', re.I)

#: X/Twitter status URLs, which need the syndication path rather than the article path.
_X_STATUS = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]+)/status/(\d+)")

#: Anything matching this is a logo, an icon, a tracking pixel or a spacer -- never the story.
_JUNK_IMAGE = re.compile(
    r"(sprite|favicon|logo|icon|avatar|placeholder|spacer|pixel|1x1|blank|badge|emoji)",
    re.I,
)

#: CDN resize parameters. Stripped so the stored URL points at the full-size image.
#:
#: A single regex replacement leaves the separator behind -- `a.jpg?width=600&fit=crop` became
#: `a.jpg&fit=crop`, a 404. Splitting the query, filtering by name, and rejoining keeps the URL
#: structurally valid.
_RESIZE_KEYS = frozenset({
    "w", "h", "width", "height", "fit", "crop", "resize", "quality", "q", "auto", "format",
})


@dataclass
class ArticleImage:
    """One image found on an article page, before it is downloaded."""

    url: str
    #: Where it came from, for the run log: og / twitter / img.
    source: str


def _absolute(base: str, url: str) -> str:
    """Resolve a possibly relative image URL against the page it came from."""
    url = (url or "").strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith(("http://", "https://", "data:")):
        return url
    return urljoin(base, url)


def _drop_resize(url: str) -> str:
    """Strip CDN resize parameters so the stored copy is the full-size image."""
    if "?" not in url:
        return url
    base, _, query = url.partition("?")
    kept = [
        part
        for part in query.split("&")
        if part and part.split("=", 1)[0].lower() not in _RESIZE_KEYS
    ]
    return base + ("?" + "&".join(kept) if kept else "")


def find_image_url(html: str, page_url: str) -> ArticleImage | None:
    """The best candidate image on a page, or None.

    Order is deliberate: a declared social card is the publisher own choice of what represents
    the story. Only when no card exists does the first img become a guess.
    """
    for pattern in _OG_IMAGE:
        match = pattern.search(html)
        if match:
            url = _absolute(page_url, match.group(1))
            if not _JUNK_IMAGE.search(url):
                return ArticleImage(_drop_resize(url), "og")

    for pattern in _TW_IMAGE:
        match = pattern.search(html)
        if match:
            url = _absolute(page_url, match.group(1))
            if not _JUNK_IMAGE.search(url):
                return ArticleImage(_drop_resize(url), "twitter")

    for raw in _IMG_TAG.findall(html):
        url = _absolute(page_url, raw)
        if not url.startswith(("http://", "https://")):
            continue
        if _JUNK_IMAGE.search(url):
            continue
        return ArticleImage(_drop_resize(url), "img")

    return None


def to_webp(data: bytes, *, width: int = 1200, quality: int = 82) -> bytes | None:
    """Re-encode to WebP at the given width. None when Pillow cannot read the bytes.

    Measured on a 3614x2034 X attachment: 226,458 bytes raw, 23,590 bytes at 1200px WebP --
    10.4% of the original. That ratio is why the collection fits in a repository.
    """
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow ships with the `media` extra
        return None

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:
        return None

    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")
    if image.width > width:
        image = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)

    buffer = io.BytesIO()
    try:
        image.save(buffer, "WEBP", quality=quality, method=6)
    except Exception:
        return None
    return buffer.getvalue()


def content_hash(data: bytes) -> str:
    """Short digest used in the filename, so identical images collide instead of piling up."""
    return hashlib.sha1(data).hexdigest()[:8]


async def fetch_bytes(
    client: httpx.AsyncClient, url: str, *, extra_headers: dict[str, str] | None = None
) -> bytes | None:
    """Download one URL. Any failure is None -- an image may never fail a run."""
    try:
        response = await client.get(
            url, timeout=20.0, follow_redirects=True, headers=extra_headers
        )
        if response.status_code != 200:
            return None
        return response.content
    except Exception:
        return None


async def fetch_page(client: httpx.AsyncClient, url: str) -> str | None:
    """Download an article page as text, for find_image_url to inspect."""
    try:
        response = await client.get(url, timeout=20.0, follow_redirects=True)
        if response.status_code != 200:
            return None
        if "html" not in response.headers.get("content-type", "").lower():
            return None
        return response.text
    except Exception:
        return None


async def image_for_article(client: httpx.AsyncClient, article_url: str) -> bytes | None:
    """Find and download one article image, re-encoded to WebP. None on any failure."""
    page = await fetch_page(client, article_url)
    if not page:
        return None
    candidate = find_image_url(page, article_url)
    if candidate is None:
        return None
    raw = await fetch_bytes(client, candidate.url)
    if raw is None or len(raw) < 1_000:
        return None
    return to_webp(raw)


async def image_for_x_post(client: httpx.AsyncClient, status_url: str) -> bytes | None:
    """Download the attachment on an X post, as WebP.

    Measured 2026-10-21: a direct GET on x.com returns a JavaScript shell whose og:image is a
    generic card, so `image_for_article` finds nothing. api.fxtwitter.com is a free, key-less
    mirror returning the post as JSON, including the full-resolution attachment on pbs.twimg.com.
    The image request itself needs a Referer, or the CDN refuses it.

    (The guide this came from recommends vxtwitter; that endpoint returned 403 when tested, so
    fxtwitter is used instead.)
    """
    match = _X_STATUS.search(status_url or "")
    if not match:
        return None
    user, status_id = match.group(1), match.group(2)
    try:
        api = f"https://api.fxtwitter.com/{user}/status/{status_id}"
        response = await client.get(api, headers={"User-Agent": _UA}, timeout=20.0)
        if response.status_code != 200:
            return None
        payload = response.json()
    except Exception:
        return None

    photos = ((payload.get("tweet") or {}).get("media") or {}).get("photos") or []
    if not photos:
        return None
    image_url = photos[0].get("url")
    if not image_url:
        return None

    raw = await fetch_bytes(client, image_url, extra_headers={"Referer": "https://x.com/"})
    if raw is None or len(raw) < 1_000:
        return None
    return to_webp(raw)


async def image_for(client: httpx.AsyncClient, article_url: str) -> bytes | None:
    """The image for any URL: the X path first, then the ordinary article path."""
    if _X_STATUS.search(article_url or ""):
        return await image_for_x_post(client, article_url)
    return await image_for_article(client, article_url)


def default_client() -> httpx.AsyncClient:
    """A client carrying a browser User-Agent, because several publishers require one."""
    return httpx.AsyncClient(
        headers={"User-Agent": _UA, "Accept": "image/*,text/html;q=0.9,*/*;q=0.8"},
        timeout=25.0,
        follow_redirects=True,
    )
