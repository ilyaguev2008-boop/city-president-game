from __future__ import annotations

import asyncio
import logging
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import aiohttp

from rss_service import FeedPreview, try_fetch_feed_sync, normalize_http_url

logger = logging.getLogger(__name__)

# Ограничиваем перебор: иначе при «тугом» сайте можно ждать минуты.
MAX_FEED_CANDIDATES = 22

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class _AlternateParser(HTMLParser):
    """Ищет <link rel=\"alternate\" type=\"...rss|atom|xml...\" href=\"...\">."""

    def __init__(self, base: str) -> None:
        super().__init__(convert_charrefs=True)
        self._base = base
        self._found: list[tuple[int, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link":
            return
        ad: dict[str, str] = {}
        for k, v in attrs:
            if k:
                ad[k.lower()] = (v or "").strip()
        rels = ad.get("rel", "").lower().split()
        if "alternate" not in rels:
            return
        href = ad.get("href", "").strip()
        if not href:
            return
        full = urljoin(self._base, href)
        typ = ad.get("type", "").lower()
        if "rss" in typ:
            prio = 0
        elif "atom" in typ:
            prio = 1
        elif "xml" in typ:
            prio = 2
        else:
            prio = 3
        self._found.append((prio, full))


def _uniq_by_priority(pairs: list[tuple[int, str]]) -> list[str]:
    pairs.sort(key=lambda x: x[0])
    out: list[str] = []
    seen: set[str] = set()
    for _, u in pairs:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


async def _build_candidates(page_url: str) -> list[str]:
    page_url = normalize_http_url(page_url)
    timeout = aiohttp.ClientTimeout(total=25)
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        try:
            async with session.get(page_url, allow_redirects=True) as resp:
                resp.raise_for_status()
                final = str(resp.url)
                body = await resp.read()
        except aiohttp.ClientError as exc:
            raise ValueError(f"Сайт не ответил ({type(exc).__name__}). Проверь ссылку.") from exc

    pairs: list[tuple[int, str]] = []
    head = body[:800].lstrip().lower()
    if head.startswith((b"<?xml", b"<rss", b"<feed")):
        pairs.append((0, final))

    text = body.decode("utf-8", errors="replace")
    if "<link" in text.lower():
        parser = _AlternateParser(final)
        try:
            parser.feed(text[:800_000])
        except Exception:
            logger.debug("HTML parse truncated or failed", exc_info=True)
        pairs.extend(parser._found)

    parsed = urlparse(final)
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    common_paths = (
        "feed",
        "?feed=rss2",
        "?feed=atom",
        "rss",
        "rss.xml",
        "feed.xml",
        "atom.xml",
        "feeds/all.rss",
        "index.xml",
        "feed/rss",
        "feed/atom",
        "blog/feed",
        "news/feed",
        "feeds/posts/default",
        "comments/feed",
        "category/news/feed",
    )
    for i, path in enumerate(common_paths):
        pairs.append((4 + i, urljoin(origin, path)))

    pairs.append((40, final))
    return _uniq_by_priority(pairs)


async def resolve_to_feed_preview(start_url: str) -> FeedPreview:
    """
    Принимает URL сайта или прямую ссылку на ленту новостей.
    Сначала пробует ленту по исходному адресу, затем ищет на странице и типовые пути.
    """
    u = normalize_http_url(start_url)
    direct = await asyncio.to_thread(try_fetch_feed_sync, u)
    if direct:
        return direct

    candidates = await _build_candidates(u)
    for cand in candidates[:MAX_FEED_CANDIDATES]:
        prev = await asyncio.to_thread(try_fetch_feed_sync, cand)
        if prev:
            return prev

    raise ValueError(
        "Не нашёл ленту новостей по этой ссылке. Попробуй другой сайт "
        "или прямую ссылку на ленту."
    )
