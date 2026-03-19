from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import feedparser


@dataclass(frozen=True)
class FeedPreview:
    title: str
    url: str
    sample_entries: list[tuple[str, str]]  # (title, link)


def _normalize_url(raw: str) -> str:
    u = raw.strip()
    if not u:
        raise ValueError("Пустая ссылка")
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Нужна ссылка с http:// или https://")
    return u


def fetch_feed_sync(url: str) -> FeedPreview:
    url = _normalize_url(url)
    parsed: Any = feedparser.parse(url)
    if not getattr(parsed, "feed", None):
        raise ValueError("Не похоже на RSS/Atom или сервер не ответил.")

    feed_title = (parsed.feed.get("title") or "").strip() or "Без названия"
    entries = list(getattr(parsed, "entries", []) or [])
    if not entries and getattr(parsed, "bozo", False):
        exc = getattr(parsed, "bozo_exception", None)
        hint = f" ({exc})" if exc else ""
        raise ValueError(f"Ошибка разбора ленты{hint}")

    sample: list[tuple[str, str]] = []
    for e in entries[:5]:
        t = (e.get("title") or "").strip()
        link = (e.get("link") or "").strip()
        if not t and not link:
            continue
        sample.append((t or "(без заголовка)", link))

    if not entries:
        raise ValueError("В ленте пока нет записей — попробуй позже или другой URL.")

    return FeedPreview(title=feed_title, url=url, sample_entries=sample)


async def fetch_feed(url: str) -> FeedPreview:
    """Загружает и разбирает RSS/Atom (feedparser в отдельном потоке)."""
    return await asyncio.to_thread(fetch_feed_sync, url)
