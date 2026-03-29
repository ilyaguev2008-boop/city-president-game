from __future__ import annotations

import asyncio
import logging

from config import load_settings
from db import (
    get_rss_monitor_state,
    list_rss_sources_for_monitor,
    news_inbox_try_add,
    upsert_rss_monitor_state,
)
from rss_entries import parse_feed_entries

logger = logging.getLogger(__name__)


async def _poll_one_source(job: dict[str, object]) -> None:
    source_id = int(job["source_id"])
    user_id = int(job["user_id"])
    rss_url = str(job["rss_url"])
    prev = await get_rss_monitor_state(source_id)
    prev_top = (prev or {}).get("last_top_entry_key")
    if isinstance(prev_top, str):
        prev_top = prev_top.strip() or None
    else:
        prev_top = None

    try:
        items = await parse_feed_entries(rss_url)
    except Exception as exc:
        logger.debug("rss monitor read failed source_id=%s: %s", source_id, exc)
        await upsert_rss_monitor_state(
            source_id,
            last_top_entry_key=prev_top,
            last_error=str(exc)[:500],
        )
        return

    if not items:
        await upsert_rss_monitor_state(
            source_id,
            last_top_entry_key=prev_top,
            last_error="empty_feed",
        )
        return

    top = items[0].entry_key
    try:
        if prev_top and prev_top != top:
            prev_still_visible = any(it.entry_key == prev_top for it in items)
            if not prev_still_visible:
                to_queue = [items[0]]
            else:
                to_queue = []
                for it in items:
                    if it.entry_key == prev_top:
                        break
                    to_queue.append(it)
            for fresh in reversed(to_queue):
                try:
                    await news_inbox_try_add(
                        user_id,
                        source_id,
                        entry_key=fresh.entry_key,
                        title=fresh.title,
                        link=fresh.link,
                        body_text=fresh.body_text,
                        image_url=fresh.image_url,
                        published_at=fresh.published_at,
                    )
                except Exception:
                    logger.exception(
                        "rss monitor: не удалось добавить в очередь user_id=%s source_id=%s",
                        user_id,
                        source_id,
                    )
    finally:
        await upsert_rss_monitor_state(
            source_id,
            last_top_entry_key=top,
            last_error=None,
        )


async def run_rss_monitor_loop() -> None:
    """
    Постоянно опрашивает все включённые источники (включая ручной режим и источники без канала).
    Новые записи только попадают в очередь news_inbox — без сообщений в чат.
    Публикация — вручную через «Опубликовать 1 пост».
    """
    await asyncio.sleep(2)
    sem = asyncio.Semaphore(8)

    async def _poll_limited(job: dict[str, object]) -> None:
        async with sem:
            try:
                await _poll_one_source(job)
            except Exception:
                logger.exception("rss monitor job source_id=%s", job.get("source_id"))

    while True:
        settings = load_settings()
        interval = settings.rss_monitor_interval_sec
        try:
            jobs = await list_rss_sources_for_monitor()
            if jobs:
                await asyncio.gather(*(_poll_limited(j) for j in jobs))
        except Exception:
            logger.exception("Сбой тика мониторинга RSS")

        await asyncio.sleep(interval)
