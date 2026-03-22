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
OG_IMAGE_SECURE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image:secure_url["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
OG_IMAGE_SECURE_RE2 = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image:secure_url["\']',
    re.IGNORECASE,
)
ARTICLE_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']article:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
JSON_LD_IMAGE_RE = re.compile(
    r'"image"\s*:\s*"([^"]+)"',
    re.IGNORECASE,
)
JSON_LD_IMAGE_ARR_RE = re.compile(
    r'"image"\s*:\s*\[\s*"([^"]+)"',
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


def _urls_from_srcset(val: str) -> list[str]:
    """Берёт URL из srcset: 'url 1x, url2 2w'."""
    out: list[str] = []
    for part in (val or "").split(","):
        part = part.strip()
        if not part:
            continue
        url = part.split()[0].strip()
        if url and not url.startswith("data:"):
            out.append(url)
    return out


def _is_probably_banner_or_icon(url: str) -> bool:
    low = url.lower()
    return any(
        x in low
        for x in (
            "spacer",
            "pixel",
            "1x1",
            "transparent",
            "emoji",
            "/icon",
            "favicon",
            "logo.svg",
            "/logo",
            "avatar",
            "sprite",
            "tracking",
            "counter",
            "doubleclick",
            "adsystem",
        )
    )


def extract_image_urls_from_html_fragment(html: str, base_url: str, *, max_images: int = 8) -> list[str]:
    """
    Картинки из HTML (описание в RSS, фрагмент страницы): img src, data-src, srcset, picture.
    """
    if not html or "<" not in html:
        return []
    found: list[str] = []
    # Обычный src
    for m in re.finditer(
        r'<img[^>]+(?:src|data-src|data-original|data-lazy-src|data-lazy|data-url)=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    ):
        u = m.group(1).strip()
        if u and not u.startswith("data:") and not _is_probably_banner_or_icon(u):
            found.append(u)
    # srcset на img / source
    for m in re.finditer(r'srcset=["\']([^"\']+)["\']', html, re.IGNORECASE):
        found.extend(_urls_from_srcset(m.group(1)))
    return _unique_cap(found, base_url, max_n=max_images)


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


def fetch_article_image_urls(page_url: str, *, timeout_sec: int = 15, max_images: int = 10) -> list[str]:
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
    for rx in (
        OG_IMAGE_RE,
        OG_IMAGE_RE2,
        OG_IMAGE_SECURE_RE,
        OG_IMAGE_SECURE_RE2,
        TW_IMAGE_RE,
        LINK_IMAGE_RE,
        ARTICLE_IMAGE_RE,
    ):
        for m in rx.finditer(html):
            found.append(m.group(1).strip())

    for m in JSON_LD_IMAGE_RE.finditer(html):
        s = m.group(1).strip()
        if s.startswith(("http://", "https://")):
            found.append(s)
    for m in JSON_LD_IMAGE_ARR_RE.finditer(html):
        s = m.group(1).strip()
        if s.startswith(("http://", "https://")):
            found.append(s)

    # Lazy-load и обычные img (расширенный набор атрибутов)
    for m in re.finditer(
        r'<img[^>]+(?:src|data-src|data-original|data-lazy-src|data-lazy|data-url)=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    ):
        u = m.group(1).strip()
        if not u.startswith("data:") and not _is_probably_banner_or_icon(u):
            found.append(u)
        if len(found) > 60:
            break

    for m in re.finditer(r'<source[^>]+srcset=["\']([^"\']+)["\']', html, re.IGNORECASE):
        found.extend(_urls_from_srcset(m.group(1)))

    return _unique_cap(found, page_url, max_n=max_images)
