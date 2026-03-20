from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.types import URLInputFile

from ai_service import rewrite_news_ru, split_for_telegram
from config import load_settings
from db import add_worker_event, is_entry_posted, list_feeding_jobs, mark_entry_posted
from rss_entries import parse_feed_entries
from text_utils import strip_urls

logger = logging.getLogger(__name__)


async def process_one_feed_job(bot: Bot, settings, job: dict[str, object]) -> bool:
    source_id = int(job["source_id"])
    user_id = int(job["user_id"])
    chat_id = int(job["chat_id"])
    rss_url = str(job["rss_url"])

    # Явно проверяем, что бот всё ещё может писать в канал.
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id=chat_id, user_id=me.id)
        can_post = bool(getattr(member, "can_post_messages", False))
        if not can_post:
            await add_worker_event(
                user_id=user_id,
                source_id=source_id,
                level="error",
                kind="channel_permission",
                message=f"Нет права публикации в канале {chat_id}",
            )
            return False
    except Exception:
        logger.exception("Ошибка проверки прав source_id=%s", source_id)
        await add_worker_event(
            user_id=user_id,
            source_id=source_id,
            level="error",
            kind="channel_access",
            message=f"Не удалось проверить канал {chat_id}",
        )
        return False

    try:
        items = await parse_feed_entries(rss_url)
    except Exception:
        logger.exception("Ошибка чтения RSS source_id=%s", source_id)
        await add_worker_event(
            user_id=user_id,
            source_id=source_id,
            level="error",
            kind="rss_read",
            message="Ошибка чтения RSS",
        )
        return False

    if not items:
        return False

    for item in items:
        if await is_entry_posted(source_id, item.entry_key):
            continue

        try:
            rewritten = await rewrite_news_ru(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.openai_model,
                title=item.title,
                body=item.body_text,
            )
        except Exception:
            logger.exception("Ошибка ИИ source_id=%s", source_id)
            await add_worker_event(
                user_id=user_id,
                source_id=source_id,
                level="error",
                kind="ai_rewrite",
                message="Ошибка ИИ при пересказе",
            )
            return False

        text = strip_urls(rewritten)
        if not text.strip():
            text = strip_urls(f"{item.title}\n\n{item.body_text}")

        photo_ok = False
        if item.image_url:
            try:
                cap = text[:1024]
                await bot.send_photo(
                    chat_id,
                    photo=URLInputFile(url=item.image_url),
                    caption=cap,
                )
                if len(text) > 1024:
                    for chunk in split_for_telegram(text[1024:]):
                        await bot.send_message(chat_id, chunk)
                photo_ok = True
            except Exception:
                logger.warning(
                    "Не удалось отправить фото, шлю только текст source_id=%s",
                    source_id,
                    exc_info=True,
                )

        if not photo_ok:
            try:
                for chunk in split_for_telegram(text):
                    await bot.send_message(chat_id, chunk)
            except Exception:
                logger.exception("Ошибка отправки в канал source_id=%s", source_id)
                await add_worker_event(
                    user_id=user_id,
                    source_id=source_id,
                    level="error",
                    kind="send_message",
                    message=f"Ошибка отправки в канал {chat_id}",
                )
                return False

        await mark_entry_posted(source_id, item.entry_key)
        await add_worker_event(
            user_id=user_id,
            source_id=source_id,
            level="info",
            kind="posted",
            message=f"Опубликована запись в канал {chat_id}",
        )
        return True

    return False


async def run_post_worker_loop(bot: Bot) -> None:
    """Фоновый цикл: новые записи из привязанных RSS → пересказ → канал."""
    await asyncio.sleep(5)
    while True:
        settings = load_settings()
        interval = settings.poll_interval_sec
        if not settings.openai_api_key:
            logger.warning("OPENAI_API_KEY не задан — автопостинг отключён")
            await asyncio.sleep(interval)
            continue

        try:
            jobs = await list_feeding_jobs()
            for job in jobs:
                await process_one_feed_job(bot, settings, job)
        except Exception:
            logger.exception("Сбой тика воркера")

        await asyncio.sleep(interval)
