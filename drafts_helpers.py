from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from post_content import BuiltPost
from rss_entries import FeedItem, parse_feed_entries
from db import is_entry_posted


@dataclass(frozen=True)
class DraftSuggestion:
    """Что показать в «Черновиках»: новая очередь или повтор верхушки ленты."""

    item: FeedItem
    kind: Literal["new", "repeat"]


@dataclass(frozen=True)
class DraftPublishSnapshot:
    """Снимок записи на момент показа черновика — чтобы опубликовать, даже если запись уже нет в свежем парсе ленты."""

    item: FeedItem
    kind: Literal["new", "repeat"]
    # Готовый пересказ и отобранные фото — то же уйдёт в канал по «Опубликовать».
    built: BuiltPost | None = None


async def get_draft_suggestion(source_id: int, rss_url: str) -> DraftSuggestion | None:
    """
    Сначала — первая запись ленты, которой ещё нет в posted_entries.
    Если все уже публиковались — всё равно возвращаем верхнюю запись ленты (kind=repeat),
    чтобы клиент мог снова выложить пересказ или дождаться обновления ленты.
    """
    items = await parse_feed_entries(rss_url)
    if not items:
        return None
    for item in items:
        if not await is_entry_posted(source_id, item.entry_key):
            return DraftSuggestion(item=item, kind="new")
    return DraftSuggestion(item=items[0], kind="repeat")
