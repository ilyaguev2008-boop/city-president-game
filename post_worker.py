from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.types import InputMediaPhoto, URLInputFile

from article_images import fetch_article_image_urls
from ai_service import rewrite_news_ru, split_for_telegram
from config import load_settings
from db import (
    add_worker_event,
    get_daily_post_count,
    get_posting_settings,
    increment_daily_post,
    is_duplicate_article_for_user,
    is_entry_posted,
    list_feeding_jobs,
    mark_entry_posted,
    remember_published_article_link,
)
from posting_rules import is_quiet_hour_local
from rss_entries import FeedItem, parse_feed_entries
from text_utils import strip_urls

logger = logging.getLogger(__name__)


async def process_one_feed_job(
    bot: Bot,
    settings,
    job: dict[str, object],
    *,
    ignore_user_posting_rules: bool = False,
    only_entry_key: str | None = None,
    force_repost: bool = False,
) -> bool:
    source_id = int(job["source_id"])
    user_id = int(job["user_id"])
    chat_id = int(job["chat_id"])
    rss_url = str(job["rss_url"])

    ps = await get_posting_settings(user_id)
    if not ignore_user_posting_rules:
        # Ручной режим: воркер не публикует в канал — только черновики в боте.
        if ps.get("posting_mode") == "manual":
            return False
        if not ps["posting_enabled"]:
            return False
        if await get_daily_post_count(user_id) >= int(ps["max_posts_per_day"]):
            return False
        if is_quiet_hour_local(
            start_hour=ps["quiet_start_hour"],
            end_hour=ps["quiet_end_hour"],
        ):
            return False

    send_images = bool(ps["send_images"])

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
        logger.exception("Ошибка чтения ленты source_id=%s", source_id)
        await add_worker_event(
            user_id=user_id,
            source_id=source_id,
            level="error",
            kind="rss_read",
            message="Ошибка чтения ленты новостей",
        )
        return False

    if not items:
        return False

    return await _publish_feed_item(
        bot,
        settings,
        job,
        items,
        send_images=send_images,
        only_entry_key=only_entry_key,
        force_repost=force_repost,
    )


async def _publish_feed_item(
    bot: Bot,
    settings,
    job: dict[str, object],
    items: list[FeedItem],
    *,
    send_images: bool,
    only_entry_key: str | None,
    force_repost: bool,
) -> bool:
    source_id = int(job["source_id"])
    user_id = int(job["user_id"])
    chat_id = int(job["chat_id"])

    if only_entry_key is not None:
        item = next((i for i in items if i.entry_key == only_entry_key), None)
        if item is None:
            return False
        if await is_entry_posted(source_id, item.entry_key) and not force_repost:
            return False
    else:
        item = None
        for candidate in items:
            if not await is_entry_posted(source_id, candidate.entry_key):
                item = candidate
                break
        if item is None:
            return False

    if (
        item.link
        and not force_repost
        and await is_duplicate_article_for_user(user_id, item.link)
    ):
        await mark_entry_posted(source_id, item.entry_key)
        await add_worker_event(
            user_id=user_id,
            source_id=source_id,
            level="info",
            kind="duplicate_skip",
            message="Та же новость уже публиковалась (совпала ссылка)",
        )
        return False

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

    def _collect_image_urls() -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        if item.image_url:
            u = item.image_url.strip()
            if u.startswith(("http://", "https://")) and u not in seen:
                seen.add(u)
                out.append(u)
        if item.link:
            try:
                for u in fetch_article_image_urls(item.link):
                    if u not in seen:
                        seen.add(u)
                        out.append(u)
                        if len(out) >= 10:
                            break
            except Exception:
                logger.debug("fetch_article_image_urls failed for %s", item.link, exc_info=True)
        return out

    photo_ok = False
    if send_images:
        image_urls = await asyncio.to_thread(_collect_image_urls)
        if len(image_urls) > 1:
            try:
                media: list[InputMediaPhoto] = []
                for i, u in enumerate(image_urls[:10]):
                    if i == 0:
                        media.append(
                            InputMediaPhoto(
                                media=URLInputFile(url=u),
                                caption=text[:1024],
                            )
                        )
                    else:
                        media.append(InputMediaPhoto(media=URLInputFile(url=u)))
                await bot.send_media_group(chat_id, media=media)
                if len(text) > 1024:
                    for chunk in split_for_telegram(text[1024:]):
                        await bot.send_message(chat_id, chunk)
                photo_ok = True
            except Exception:
                logger.warning(
                    "Не удалось отправить группу фото, пробую одно фото source_id=%s",
                    source_id,
                    exc_info=True,
                )
        if not photo_ok and image_urls:
            try:
                cap = text[:1024]
                await bot.send_photo(
                    chat_id,
                    photo=URLInputFile(url=image_urls[0]),
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
    if item.link:
        await remember_published_article_link(user_id, item.link)
    await increment_daily_post(user_id)
    await add_worker_event(
        user_id=user_id,
        source_id=source_id,
        level="info",
        kind="posted",
        message=f"Опубликована запись в канал {chat_id}",
    )
    return True


async def run_post_worker_loop(bot: Bot) -> None:
    """Фоновый цикл: новые записи из привязанных источников новостей → пересказ → канал."""
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
