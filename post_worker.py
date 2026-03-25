from __future__ import annotations

import asyncio
import logging
from typing import NamedTuple

from io import BytesIO

from aiogram import Bot
from aiogram.types import BufferedInputFile, InputMediaPhoto, URLInputFile

from channel_permissions import bot_can_post_to_channel
from ai_service import split_for_telegram
from config import load_settings
from telegram_helpers import get_bot_user_id
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
from post_content import BuiltPost, build_feed_post_content
from rss_entries import FeedItem, parse_feed_entries

logger = logging.getLogger(__name__)


class PublishOutcome(NamedTuple):
    ok: bool
    """Короткий текст для пользователя в чате с ботом; None — не показывать (фоновый воркер)."""
    user_message: str | None = None


async def process_one_feed_job(
    bot: Bot,
    settings,
    job: dict[str, object],
    *,
    ignore_user_posting_rules: bool = False,
    only_entry_key: str | None = None,
    force_repost: bool = False,
    fallback_feed_item: FeedItem | None = None,
    prebuilt: BuiltPost | None = None,
    user_photo_file_id: str | None = None,
) -> PublishOutcome:
    source_id = int(job["source_id"])
    user_id = int(job["user_id"])
    chat_id = int(job["chat_id"])
    rss_url = str(job["rss_url"])

    ps = await get_posting_settings(user_id)
    if not ignore_user_posting_rules:
        # Ручной режим: воркер не публикует в канал — только черновики в боте.
        if ps.get("posting_mode") == "manual":
            return PublishOutcome(False)
        # По умолчанию автопост в канал выключен (см. ALLOW_AUTO_POSTING в .env).
        if not settings.allow_auto_posting:
            return PublishOutcome(False)
        if not ps["posting_enabled"]:
            return PublishOutcome(False)
        if await get_daily_post_count(user_id) >= int(ps["max_posts_per_day"]):
            return PublishOutcome(False)
        if is_quiet_hour_local(
            start_hour=ps["quiet_start_hour"],
            end_hour=ps["quiet_end_hour"],
        ):
            return PublishOutcome(False)

    send_images = bool(ps["send_images"])

    # Явно проверяем, что бот всё ещё может писать в канал.
    try:
        member = await bot.get_chat_member(
            chat_id=chat_id,
            user_id=await get_bot_user_id(bot),
        )
        can_post = bot_can_post_to_channel(member)
        if not can_post:
            await add_worker_event(
                user_id=user_id,
                source_id=source_id,
                level="error",
                kind="channel_permission",
                message=f"Нет права публикации в канале {chat_id}",
            )
            return PublishOutcome(
                False,
                "У бота нет права «Публикация сообщений» в этом канале. Открой админов канала и включи его.",
            )
    except Exception:
        logger.exception("Ошибка проверки прав source_id=%s", source_id)
        await add_worker_event(
            user_id=user_id,
            source_id=source_id,
            level="error",
            kind="channel_access",
            message=f"Не удалось проверить канал {chat_id}",
        )
        return PublishOutcome(
            False,
            "Не удалось проверить канал в Telegram (неверный канал или бот удалён из админов).",
        )

    try:
        items = await parse_feed_entries(rss_url)
    except Exception:
        logger.exception("Ошибка чтения ленты source_id=%s", source_id)
        if not (
            fallback_feed_item is not None
            and only_entry_key is not None
            and fallback_feed_item.entry_key == only_entry_key
        ):
            await add_worker_event(
                user_id=user_id,
                source_id=source_id,
                level="error",
                kind="rss_read",
                message="Ошибка чтения ленты новостей",
            )
            return PublishOutcome(False, "Не удалось прочитать ленту новостей.")
        items = [fallback_feed_item]

    if not items:
        if (
            fallback_feed_item is not None
            and only_entry_key is not None
            and fallback_feed_item.entry_key == only_entry_key
        ):
            items = [fallback_feed_item]
        else:
            return PublishOutcome(False, "Лента новостей пуста или недоступна.")

    return await _publish_feed_item(
        bot,
        settings,
        job,
        items,
        send_images=send_images,
        only_entry_key=only_entry_key,
        force_repost=force_repost,
        fallback_feed_item=fallback_feed_item,
        prebuilt=prebuilt,
        user_photo_file_id=user_photo_file_id,
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
    fallback_feed_item: FeedItem | None = None,
    prebuilt: BuiltPost | None = None,
    user_photo_file_id: str | None = None,
) -> PublishOutcome:
    source_id = int(job["source_id"])
    user_id = int(job["user_id"])
    chat_id = int(job["chat_id"])

    if only_entry_key is not None:
        item = next((i for i in items if i.entry_key == only_entry_key), None)
        if item is None:
            if (
                fallback_feed_item is not None
                and fallback_feed_item.entry_key == only_entry_key
            ):
                item = fallback_feed_item
            else:
                return PublishOutcome(False, "Не удалось сопоставить запись с лентой.")
        if await is_entry_posted(source_id, item.entry_key) and not force_repost:
            return PublishOutcome(
                False,
                "Эта запись уже отмечена как опубликованная. Обнови черновик.",
            )
    else:
        item = None
        for candidate in items:
            if not await is_entry_posted(source_id, candidate.entry_key):
                item = candidate
                break
        if item is None:
            return PublishOutcome(False, "В ленте нет новых неопубликованных записей.")

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
        return PublishOutcome(
            False,
            "Такая новость уже публиковалась у тебя (совпала ссылка с другим постом).",
        )

    if prebuilt is not None:
        text = prebuilt.text
        image_urls = list(prebuilt.image_urls) if send_images else []
    else:
        try:
            built = await build_feed_post_content(
                item,
                settings,
                send_images=send_images,
                polish_english=settings.post_polish_english_to_russian,
            )
        except RuntimeError as exc:
            return PublishOutcome(
                False,
                str(exc) or "Нет OPENAI_API_KEY. Добавь ключ или выставь OPENAI_FALLBACK_PLAIN_TEXT=1.",
            )
        except Exception as exc:
            logger.exception("Ошибка сборки поста source_id=%s", source_id)
            await add_worker_event(
                user_id=user_id,
                source_id=source_id,
                level="error",
                kind="ai_rewrite",
                message=f"Ошибка при подготовке поста: {exc}",
            )
            err_txt = str(exc).strip()
            if len(err_txt) > 350:
                err_txt = err_txt[:350] + "…"
            return PublishOutcome(
                False,
                f"Не удалось подготовить пост: {err_txt}",
            )
        text = built.text
        image_urls = list(built.image_urls) if send_images else []

    photo_ok = False
    if user_photo_file_id:
        try:
            buf = BytesIO()
            await bot.download(file=user_photo_file_id, destination=buf)
            buf.seek(0)
            raw = buf.read()
            if not raw:
                raise RuntimeError("empty download")
            photo = BufferedInputFile(raw, filename="post.jpg")
            cap = text[:1024]
            await bot.send_photo(chat_id, photo=photo, caption=cap)
            if len(text) > 1024:
                for chunk in split_for_telegram(text[1024:]):
                    await bot.send_message(chat_id, chunk)
            photo_ok = True
        except Exception:
            logger.exception(
                "Ошибка отправки фото из Telegram file_id source_id=%s",
                source_id,
            )
            await add_worker_event(
                user_id=user_id,
                source_id=source_id,
                level="error",
                kind="send_photo",
                message="Не удалось отправить фото пользователя в канал",
            )
            return PublishOutcome(
                False,
                "Не удалось отправить фото в канал. Попробуй другое изображение или проверь права бота.",
            )
    elif send_images:
        max_img = settings.post_max_images
        if len(image_urls) > 1:
            try:
                media: list[InputMediaPhoto] = []
                for i, u in enumerate(image_urls[:max_img]):
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
            return PublishOutcome(
                False,
                "Telegram не принял сообщение в канал (ограничение, длина текста или сеть).",
            )

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
    return PublishOutcome(True)


async def run_post_worker_loop(bot: Bot) -> None:
    """Фоновый цикл: новые записи из привязанных источников новостей → пересказ → канал."""
    await asyncio.sleep(5)
    sem = asyncio.Semaphore(4)

    async def _run_one(job: dict[str, object], st: object) -> None:
        async with sem:
            try:
                await process_one_feed_job(bot, st, job)
            except Exception:
                logger.exception("Сбой задачи source_id=%s", job.get("source_id"))

    while True:
        settings = load_settings()
        interval = settings.poll_interval_sec
        has_key = bool((settings.openai_api_key or "").strip())
        if not has_key and not settings.openai_fallback_plain_text:
            logger.warning(
                "OPENAI_API_KEY не задан и OPENAI_FALLBACK_PLAIN_TEXT=0 — автопостинг отключён"
            )
            await asyncio.sleep(interval)
            continue

        try:
            jobs = await list_feeding_jobs()
            if jobs:
                await asyncio.gather(*(_run_one(j, settings) for j in jobs))
        except Exception:
            logger.exception("Сбой тика воркера")

        await asyncio.sleep(interval)
