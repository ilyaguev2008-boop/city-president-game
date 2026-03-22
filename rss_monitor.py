from __future__ import annotations

import asyncio
import logging
from html import escape

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import load_settings
from db import (
    add_worker_event,
    get_rss_monitor_state,
    list_rss_sources_for_monitor,
    upsert_rss_monitor_state,
)
from rss_entries import parse_feed_entries

logger = logging.getLogger(__name__)


async def _poll_one_source(bot: Bot, job: dict[str, object]) -> None:
    source_id = int(job["source_id"])
    user_id = int(job["user_id"])
    rss_url = str(job["rss_url"])
    feed_title = (job.get("feed_title") or "").strip() or "—"
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
            try:
                await add_worker_event(
                    user_id=user_id,
                    source_id=source_id,
                    level="info",
                    kind="rss_fresh",
                    message="В ленте появились новые записи (верхняя запись обновилась).",
                )
                text = (
                    "📰 <b>У нас новый пост в черновиках — проверьте его!</b>\n\n"
                    f"Источник <b>#{source_id}</b>: {escape(feed_title)}"
                )
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="Открыть черновик",
                                callback_data=f"d:v:{source_id}",
                            ),
                            InlineKeyboardButton(
                                text="Все черновики",
                                callback_data="menu:drafts",
                            ),
                        ],
                    ]
                )
                await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=kb)
            except Exception:
                logger.exception(
                    "rss monitor: событие или уведомление user_id=%s source_id=%s",
                    user_id,
                    source_id,
                )
    finally:
        await upsert_rss_monitor_state(
            source_id,
            last_top_entry_key=top,
            last_error=None,
        )


async def run_rss_monitor_loop(bot: Bot) -> None:
    """
    Постоянно опрашивает все включённые источники (включая ручной режим и источники без канала).
    Обновляет «верхушку» ленты в БД и пишет событие в «Статус», когда появляются новые материалы.
    При появлении новой верхней записи шлёт пользователю напоминание в личку.
    """
    await asyncio.sleep(2)
    while True:
        settings = load_settings()
        interval = settings.rss_monitor_interval_sec
        try:
            jobs = await list_rss_sources_for_monitor()
            for job in jobs:
                await _poll_one_source(bot, job)
                await asyncio.sleep(0.05)
        except Exception:
            logger.exception("Сбой тика мониторинга RSS")

        await asyncio.sleep(interval)
