from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import feedparser

from text_utils import clean_whitespace, strip_html


@dataclass(frozen=True)
class FeedItem:
    entry_key: str
    title: str
    body_text: str
    link: str
    image_url: str | None


def _entry_key_from_feed(entry: dict[str, Any]) -> str:
    gid = entry.get("id") or entry.get("guid") or ""
    if isinstance(gid, dict):
        gid = str(gid.get("value") or gid.get("id") or "")
    if isinstance(gid, str) and gid.strip():
        return gid.strip()[:500]
    link = (entry.get("link") or "").strip()
    return link[:500] if link else ""


def _extract_image_url(entry: dict[str, Any]) -> str | None:
    mt = entry.get("media_thumbnail")
    if isinstance(mt, list) and mt:
        u = mt[0].get("url") if isinstance(mt[0], dict) else None
        if u:
            return str(u).strip()
    for mc in entry.get("media_content") or []:
        if not isinstance(mc, dict):
            continue
        typ = (mc.get("type") or "").lower()
        if typ.startswith("image") or mc.get("medium") == "image":
            u = mc.get("url")
            if u:
                return str(u).strip()
    for enc in entry.get("enclosures") or []:
        if not isinstance(enc, dict):
            continue
        if (enc.get("type") or "").startswith("image"):
            u = enc.get("href") or enc.get("url")
            if u:
                return str(u).strip()
    for link in entry.get("links") or []:
        if not isinstance(link, dict):
            continue
        if (link.get("type") or "").startswith("image"):
            u = link.get("href")
            if u:
                return str(u).strip()
    return None


def parse_feed_entries_sync(feed_url: str) -> list[FeedItem]:
    parsed: Any = feedparser.parse(feed_url)
    raw_entries = list(getattr(parsed, "entries", []) or [])
    out: list[FeedItem] = []
    for e in raw_entries:
        if not isinstance(e, dict):
            continue
        key = _entry_key_from_feed(e)
        if not key:
            continue
        title = (e.get("title") or "").strip()
        link = (e.get("link") or "").strip()
        summary = e.get("summary") or e.get("description") or ""
        summary = clean_whitespace(strip_html(str(summary)))
        body = summary or title
        img = _extract_image_url(e)
        out.append(
            FeedItem(
                entry_key=key,
                title=title,
                body_text=body,
                link=link,
                image_url=img,
            )
        )
    return out


async def parse_feed_entries(feed_url: str) -> list[FeedItem]:
    return await asyncio.to_thread(parse_feed_entries_sync, feed_url)
