from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen
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
    if " " in u or "\n" in u:
        raise ValueError("Укажи ссылку одной строкой без пробелов и переносов")
    added_scheme = False
    if not re.match(r"^https?://", u, re.IGNORECASE):
        u = "https://" + u.lstrip("/")
        added_scheme = True
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Нужна ссылка с http:// или https://")
    host = (parsed.netloc or "").split("@")[-1].split(":")[0]
    if not host:
        raise ValueError("Некорректная ссылка")
    if added_scheme and "." not in host and host.lower() not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError(
            "Похоже на неполный адрес. Укажи как в браузере: site.ru или https://site.ru"
        )
    return u


def normalize_http_url(raw: str) -> str:
    """Публичная обёртка для нормализации URL (сайт или лента)."""
    return _normalize_url(raw)


def try_normalize_http_url(raw: str) -> str | None:
    """Как normalize_http_url, но без исключения — для распознавания ввода в чате."""
    try:
        return normalize_http_url(raw)
    except ValueError:
        return None


def _download_url_bytes(url: str, *, timeout_sec: int = 12) -> tuple[str, bytes]:
    req = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
        },
    )
    try:
        with urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read()
            final_url = resp.geturl() or url
            return final_url, body
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Сервер не отвечает или блокирует доступ ({type(exc).__name__}).") from exc


def try_fetch_feed_sync(url: str) -> FeedPreview | None:
    """Пробует скачать ленту; при неудаче возвращает None (без исключения)."""
    try:
        return fetch_feed_sync(url)
    except ValueError:
        return None


def fetch_feed_sync(url: str) -> FeedPreview:
    url = _normalize_url(url)
    final_url, body = _download_url_bytes(url)
    parsed: Any = feedparser.parse(body)
    if not getattr(parsed, "feed", None):
        raise ValueError("Не похоже на ленту новостей или сервер не ответил.")

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

    return FeedPreview(title=feed_title, url=final_url, sample_entries=sample)


async def fetch_feed(url: str) -> FeedPreview:
    """Загружает и разбирает ленту новостей (feedparser в отдельном потоке)."""
    return await asyncio.to_thread(fetch_feed_sync, url)
