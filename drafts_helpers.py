from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from post_content import BuiltPost
from rss_entries import FeedItem, parse_feed_entries
from db import is_entry_posted, news_inbox_next_unposted


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


def _feed_item_from_inbox_row(row: dict[str, object]) -> FeedItem:
    img_raw = row.get("image_url")
    img = str(img_raw).strip() if img_raw else None
    pa = row.get("published_at")
    return FeedItem(
        entry_key=str(row.get("entry_key") or "")[:500],
        title=str(row.get("title") or ""),
        body_text=str(row.get("body_text") or ""),
        link=str(row.get("link") or ""),
        image_url=img or None,
        published_at=str(pa).strip() if pa else None,
    )


async def get_draft_suggestion(user_id: int, source_id: int, rss_url: str) -> DraftSuggestion | None:
    """
    Сначала — очередь мониторинга (news_inbox): самая ранняя ещё не опубликованная запись.
    Иначе — первая запись ленты, которой ещё нет в posted_entries.
    Если все уже публиковались — всё равно возвращаем верхнюю запись ленты (kind=repeat),
    чтобы клиент мог снова выложить пересказ или дождаться обновления ленты.
    """
    inbox_row = await news_inbox_next_unposted(user_id, source_id)
    if inbox_row:
        item = _feed_item_from_inbox_row(inbox_row)
        if item.entry_key.strip():
            return DraftSuggestion(item=item, kind="new")

    items = await parse_feed_entries(rss_url)
    if not items:
        return None
    for item in items:
        if not await is_entry_posted(source_id, item.entry_key):
            return DraftSuggestion(item=item, kind="new")
    return DraftSuggestion(item=items[0], kind="repeat")
