from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

# og:image, twitter:image, первые img в разметке
OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
OG_IMAGE_RE2 = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    re.IGNORECASE,
)
TW_IMAGE_RE = re.compile(
    r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
LINK_IMAGE_RE = re.compile(
    r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def _abs_url(base: str, u: str) -> str | None:
    u = unescape((u or "").strip())
    if not u or u.startswith("data:") or u.startswith("javascript:"):
        return None
    if u.startswith("//"):
        p = urlparse(base)
        return f"{p.scheme}:{u}" if p.scheme else None
    if u.startswith("http://") or u.startswith("https://"):
        return u
    try:
        return urljoin(base, u)
    except Exception:
        return None


def _unique_cap(urls: list[str], base: str, *, max_n: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in urls:
        a = _abs_url(base, raw)
        if not a or a in seen:
            continue
        seen.add(a)
        out.append(a)
        if len(out) >= max_n:
            break
    return out


def fetch_article_image_urls(page_url: str, *, timeout_sec: int = 12, max_images: int = 10) -> list[str]:
    """
    Подтягивает URL картинок со страницы статьи (og:image, twitter:image и т.д.).
    Лента RSS часто даёт только превью — здесь добираем то, что указано на сайте.
    """
    page_url = (page_url or "").strip()
    if not page_url or not page_url.startswith(("http://", "https://")):
        return []
    req = Request(
        page_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read()
            charset = None
            hdrs = getattr(resp, "headers", None)
            if hdrs is not None and hasattr(hdrs, "get_content_charset"):
                charset = hdrs.get_content_charset()
    except Exception:
        return []
    try:
        html = raw.decode(charset or "utf-8", errors="ignore")
    except Exception:
        html = raw.decode("utf-8", errors="ignore")
    if len(html) > 2_000_000:
        html = html[:2_000_000]

    found: list[str] = []
    for rx in (OG_IMAGE_RE, OG_IMAGE_RE2, TW_IMAGE_RE, LINK_IMAGE_RE):
        for m in rx.finditer(html):
            found.append(m.group(1).strip())

    # Резерв: img в контенте (много шума — берём первые несколько подходящих)
    for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE):
        u = m.group(1).strip()
        low = u.lower()
        if any(
            x in low
            for x in (
                "spacer",
                "pixel",
                "1x1",
                "transparent",
                "emoji",
                "icon",
                "logo",
                "avatar",
            )
        ):
            continue
        found.append(u)
        if len(found) > 40:
            break

    return _unique_cap(found, page_url, max_n=max_images)
