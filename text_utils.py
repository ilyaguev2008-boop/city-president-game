from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

TAG_RE = re.compile(r"<[^>]+>")
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def strip_html(html: str) -> str:
    if not html:
        return ""
    return TAG_RE.sub(" ", html)


def clean_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def strip_urls(text: str) -> str:
    if not text:
        return ""
    return clean_whitespace(URL_RE.sub("", text))


_TRACKING_QUERY_KEYS = frozenset(
    k.lower()
    for k in (
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
    )
)


def normalize_article_link(url: str) -> str:
    """Одинаковые новости с разных источников часто отличаются только метками в URL."""
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        p = urlparse(raw)
        if p.scheme not in ("http", "https") or not p.netloc:
            return ""
        netloc = p.netloc.lower()
        path = p.path or "/"
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")
        q = parse_qs(p.query, keep_blank_values=False)
        q = {k: v for k, v in q.items() if k.lower() not in _TRACKING_QUERY_KEYS}
        query = urlencode(sorted(q.items()), doseq=True)
        return urlunparse((p.scheme.lower(), netloc, path, p.params, query, ""))
    except Exception:
        return ""
