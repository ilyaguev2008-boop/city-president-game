from __future__ import annotations

import re

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
