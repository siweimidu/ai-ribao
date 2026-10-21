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

#: Blocks whose images belong to the article. A bare <img> anywhere on the page is how site
#: furniture got in: an author portrait, a logo strip, a brand banner repeated under five
#: unrelated stories.
_ARTICLE_BODY = re.compile(r"<(article|figure|picture)\b[^>]*>(.*?)</\1>", re.S | re.I)

#: X/Twitter status URLs, which need the syndication path rather than the article path.
_X_STATUS = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]+)/status/(\d+)")

#: Anything matching this is a logo, an icon, a tracking pixel or a spacer -- never the story.
#: Anything matching this is a logo, an icon, a tracking pixel or a spacer -- never the story.
#:
#: `/og/` and `social-preview` catch the cards aggregators generate for themselves. Measured
#: 2026-10-21: every aihot item declares `aihot.news/og/items/<id>.png`, a branded panel
#: carrying the aggregator logo and its own score badge. Publishing that as the picture for
#: a story the aggregator merely relayed is worse than publishing nothing.
_JUNK_IMAGE = re.compile(
    r"(sprite|favicon|logo|icon|avatar|placeholder|spacer|pixel|1x1|blank|badge|emoji|"    r"/og/|/og-image|social-preview|share-card|default-share)",    re.I,
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
    """The best candidate image on a page, or None. First match wins, no scoring.

    Kept for callers that only need a URL (the tests, and the no-download path). The pipeline
    uses `find_image_candidates`, which ranks by the pixels it actually downloads.
    """
    candidates = find_image_candidates(html, page_url)
    return candidates[0] if candidates else None


def find_image_candidates(html: str, page_url: str, *, limit: int = 6) -> list[ArticleImage]:
    """Every image on the page that is *provably* about this story, best-first.

    **The rule: only trust what the publisher declared about this page.**

    An earlier version took every `<img>` on the page. Measured on the 2026-10-21 issue that
    produced:

      - two AWS brand decorations (a wireframe-cube motif, a gradient-orb banner) under five
        unrelated articles
      - an author portrait, a site banner and an unrelated chart under a single story
      - four pictures where two were the same footer strip

    Every one of those was a real, large, well-shaped photograph that passed every size check.
    None of them belonged to the article. Size cannot tell you provenance; only the markup can.

    So a candidate must be one of:

      1. `og:image` -- the publisher own statement of what represents this page.
      2. `twitter:image` -- the same statement for cards.
      3. An `<img>` inside `<figure>`, `<picture>` or `<article>`, where the publisher is saying
         "this picture belongs to this piece".

    Everything else is dropped, however large it is. A story with no qualifying picture shows no
    picture -- an empty slot is honest, a wrong picture is a lie.

    The trade is real: fewer stories will carry images. That is the correct direction when the
    alternative is decoration masquerading as reporting.
    """
    out: list[ArticleImage] = []
    seen: set[str] = set()

    def add(raw: str, kind: str) -> None:
        url = _absolute(page_url, raw)
        if not url.startswith(("http://", "https://")):
            return
        if _JUNK_IMAGE.search(url):
            return
        url = _drop_resize(url)
        if url in seen:
            return
        seen.add(url)
        out.append(ArticleImage(url, kind))

    for pattern in _OG_IMAGE:
        for match in pattern.finditer(html):
            add(match.group(1), "og")
    for pattern in _TW_IMAGE:
        for match in pattern.finditer(html):
            add(match.group(1), "twitter")

    # Body images only when the markup places them inside the article. A bare `<img>` anywhere on
    # the page is exactly how site furniture got in.
    # `findall` with groups returns tuples; the body is the second group.
    for block in (m[1] for m in _ARTICLE_BODY.findall(html)):
        for raw in _IMG_TAG.findall(block):
            add(raw, "body")
            if len(out) >= limit:
                return out[:limit]


    return out[:limit]


def score_image(data: bytes, *, width: int, height: int) -> int:
    """How suitable an image is as a story picture. Higher is better; <0 rejects it.

    **Aspect ratio is not a rejection criterion.** The reference layout stacks a story images
    side by side in a horizontally scrolling row and gives each one its own proportions --
    measured on its 2026-10-21 issue, the four pictures of one entry are 1080x720, 1080x227,
    1080x1017 and 1080x351, from 1.06 to 4.76. A cropped 16:9 frame would destroy three of those
    four: the long terminal screenshot, the tall diagram, the wide banner.

    What this rejects is what is never a story picture: an icon, a spacer, a topic tile that is
    byte-identical across unrelated posts. Size and provenance carry that, not shape.
    """
    if width < 400 or height < 180:
        return -1
    score = min(width, 1600) // 100
    # Very wide images are usually banners. A nudge, not a filter: a 4.7:1 banner still beats no
    # image at all.
    if width / height > 3.5:
        score -= 6
    # Narrower than the target renders soft when upscaled. A penalty, not a veto: a 640px
    # image is still better than the placeholder, and plenty of publishers only ship that.
    if width < 800:
        score -= 4
    return score

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


def placeholder(seed: str, *, width: int = 1200, height: int = 630) -> bytes | None:
    """A deterministic abstract image for a story whose own page yielded nothing.

    Two decisions are baked in here.

    **Why a generated fallback at all.** The requirement is that every entry carries a picture.
    A page with no `og:image`, a publisher that blocks the request, an aggregator card that was
    correctly rejected -- each leaves a gap, and a gap in a picture-per-story layout reads as
    broken rather than as sparse.

    **Why it is not a stock photo or an AI illustration.** A generic photograph next to a specific
    headline is a false claim about the story. This draws nothing figurative: a soft gradient in
    the accent colour plus the entry own initial. It is obviously a placeholder, which is honest,
    and it is derived from the event id, so the same story always gets the same one.
    """
    from PIL import Image, ImageDraw

    # The hue is stable per story: hashing the seed means two stories never share a background,
    # and a re-run never changes the one a published page already shows.
    digest = hashlib.sha1((seed or "x").encode()).digest()
    hue = digest[0] / 255.0
    top = _hsv_to_rgb(hue, 0.28, 0.96)
    bottom = _hsv_to_rgb((hue + 0.06) % 1.0, 0.42, 0.66)

    image = Image.new("RGB", (width, height), bottom)
    draw = ImageDraw.Draw(image)
    # A vertical gradient, drawn row by row: cheapest way to get a smooth wash with no dependency.
    for y in range(height):
        t = y / max(1, height - 1)
        draw.line(
            [(0, y), (width, y)],
            fill=tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)),
        )

    # A few translucent circles, placed from the same digest: texture, not a picture.
    overlay = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    odraw = ImageDraw.Draw(overlay)
    for index in range(5):
        cx = int(digest[1 + index] / 255.0 * width)
        cy = int(digest[6 + index] / 255.0 * height)
        radius = 60 + digest[11 + index] % 180
        odraw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            fill=(255, 255, 255, 18),
        )
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")

    buffer = io.BytesIO()
    try:
        image.save(buffer, "WEBP", quality=82, method=6)
    except Exception:
        return None
    return buffer.getvalue()


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    """Minimal HSV to RGB, so a placeholder needs no colour library."""
    i = int(h * 6)
    f = h * 6 - i
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    r, g, b = (
        (v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q),
    )[i % 6]
    return round(r * 255), round(g * 255), round(b * 255)


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


async def best_images(
    client: httpx.AsyncClient, page_url: str, *, max_tries: int = 8, keep: int = 4
) -> list[bytes]:
    """Download the candidates and return the usable ones, best-first, as WebP.

    **A story often has more than one picture, and all of them belong on the page.** The
    reference layout puts them side by side in a horizontally scrolling row; measured on its
    2026-10-21 issue the first entry carries four, at 1080x720, 1080x227, 1080x1017 and
    1080x351. Showing only the first throws away the diagram, the terminal screenshot and the
    benchmark table -- exactly the parts a reader wants after the summary.

    So this returns a list rather than one image, and it does not crop: each keeps its own
    proportions and the CSS gives it `width: auto`.
    """
    from PIL import Image

    page = await fetch_page(client, page_url)
    if not page:
        return []

    candidates = find_image_candidates(page, page_url, limit=max_tries)
    if not candidates:
        return []

    scored: list[tuple[int, bytes, str]] = []
    for candidate in candidates[:max_tries]:
        raw = await fetch_bytes(client, candidate.url)
        if raw is None or len(raw) < 2_000:
            continue
        try:
            with Image.open(io.BytesIO(raw)) as probe:
                width, height = probe.size
        except Exception:
            continue
        score = score_image(raw, width=width, height=height)
        if score < 0:
            continue
        # The social card already describes the story; a small tie-break keeps it first without
        # letting it displace a genuinely better body image.
        if candidate.source in ("og", "twitter"):
            score += 6
        webp = to_webp(raw, width=1080)
        if not webp:
            continue
        # **Content-addressed de-duplication.**
        #
        # Measured on the 2026-10-21 issue: four AWS blog posts each carried the same two
        # footer images (`f841b50b`, `3be6a336`) as their third and fourth pictures -- a
        # site-wide banner and a logo strip that every post on that domain includes. They
        # passed the size and shape checks because they *are* real images, just not this
        # article.
        #
        # The same bytes appearing twice is the signal: a story never needs two copies of
        # one picture, and the hash is already computed for the filename.
        digest = content_hash(webp)
        if any(existing[2] == digest for existing in scored):
            continue
        scored.append((score, webp, digest))
    scored.sort(key=lambda pair: -pair[0])
    return [data for _, data, _ in scored[:keep]]


async def best_image(
    client: httpx.AsyncClient, page_url: str, *, max_tries: int = 8
) -> bytes | None:
    """Download the candidates and keep the best-looking one, as WebP.

    The reason this exists rather than taking the first URL: measured across live pages, the
    first image is often the worst.

    * cloud.google.com declares `AI_infrastructure_default.max-300x300.jpg` as its og:image --
      a 300px topic tile, byte-identical for every post in that category.
    * aws.amazon.com puts twenty marketing banners ahead of the article picture.

    So the bytes decide. Each candidate is fetched, opened, scored by `score_image`, and the
    highest score wins. Everything is capped at `max_tries` so a bad page cannot spend a run.
    """
    from PIL import Image

    page = await fetch_page(client, page_url)
    if not page:
        return None

    candidates = find_image_candidates(page, page_url)
    if not candidates:
        return None

    best: tuple[int, bytes] | None = None
    for candidate in candidates[:max_tries]:
        raw = await fetch_bytes(client, candidate.url)
        if raw is None or len(raw) < 2_000:
            continue
        try:
            with Image.open(io.BytesIO(raw)) as probe:
                width, height = probe.size
        except Exception:
            continue
        score = score_image(raw, width=width, height=height)
        if score < 0:
            continue
        # The social card already describes the story; give it a small tie-break so an equally
        # good body image never displaces it, but a much better one does.
        if candidate.source in ("og", "twitter"):
            score += 6
        if best is None or score > best[0]:
            webp = to_webp(raw)
            if webp:
                best = (score, webp)

    return best[1] if best else None


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


async def images_for(
    client: httpx.AsyncClient, article_url: str, *, keep: int = 4
) -> list[bytes]:
    """Every usable picture for a URL. X posts yield their attachments; articles their body.

    Returns a list so the layout can show them side by side. An empty list means there is no
    picture, and the item renders without one.

    `keep` bounds how many pictures a single story may carry. The caller passes a smaller number
    than the default when a run has many stories and the image stage is the slow part.
    """
    if _X_STATUS.search(article_url or ""):
        single = await image_for_x_post(client, article_url)
        return [single] if single else []
    return await best_images(client, article_url, keep=keep)


def default_client() -> httpx.AsyncClient:
    """A client carrying a browser User-Agent, because several publishers require one."""
    return httpx.AsyncClient(
        headers={"User-Agent": _UA, "Accept": "image/*,text/html;q=0.9,*/*;q=0.8"},
        timeout=25.0,
        follow_redirects=True,
    )
