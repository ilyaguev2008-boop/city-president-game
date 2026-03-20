from __future__ import annotations

from rss_entries import FeedItem, parse_feed_entries
from db import is_entry_posted


async def get_next_pending_item(source_id: int, rss_url: str) -> FeedItem | None:
    """Первая запись ленты, которой ещё нет в posted_entries."""
    items = await parse_feed_entries(rss_url)
    for item in items:
        if not await is_entry_posted(source_id, item.entry_key):
            return item
    return None
