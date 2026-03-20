from __future__ import annotations

import asyncio
import logging
import re
from html import escape

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message

from ai_service import complete_chat, split_for_telegram
from config import load_settings
from db import (
    add_channel,
    add_rss_source,
    delete_channel,
    delete_rss_source,
    ensure_user,
    get_daily_post_count,
    get_feed_job_for_user,
    get_last_event_for_user,
    get_posting_settings,
    get_user_stats,
    init_db,
    list_channels,
    list_rss_sources,
    set_rss_source_channel,
    update_posting_settings,
)
from feed_discovery import resolve_to_feed_preview
from rss_service import try_normalize_http_url
from keyboards import (
    back_to_main_kb,
    channels_kb,
    main_menu_kb,
    posting_settings_kb,
    sources_kb,
)
from post_worker import process_one_feed_job, run_post_worker_loop

TG_LINK_RE = re.compile(r"^(?:https?://)?(?:t\.me/|telegram\.me/)?@?([A-Za-z0-9_]{5,})/?$", re.IGNORECASE)
pending_action_by_user: dict[int, str] = {}


def looks_like_single_line_site_url(text: str) -> bool:
    """Одна строка, похожая на URL сайта или ленты (в т.ч. без https://)."""
    t = (text or "").strip()
    if not t or len(t) > 4000:
        return False
    if try_normalize_http_url(t) is None:
        return False
    tl = t.lower()
    # Ссылки на Telegram-каналы обрабатываются в «Мои каналы», не как лента новостей.
    if "t.me/" in tl or "telegram.me/" in tl:
        return False
    return True


def main_menu_text(name: str, *, key_hint: str) -> str:
    return (
        f"Привет, {name}!\n\n"
        "Это бот **автопостинга в Telegram-каналы**: материалы из **твоих** источников новостей "
        "(через ленту сайта), пересказ на русском, пост без лишних ссылок и с одной картинкой.\n\n"
        "**Источник новостей:** пришли в чат **одной строкой** ссылку на **сайт** (https://…) — бот "
        "попробует найти ленту сам. Или открой раздел «Источники новостей».\n\n"
        "Другой вопрос по боту — просто напиши текстом (не одной только ссылкой)."
        f"{key_hint}"
    )


async def render_sources_html(user_id: int) -> str:
    rows = await list_rss_sources(user_id)
    if not rows:
        return (
            "<b>Источники новостей</b>\n\n"
            "Пока пусто.\n\n"
            "• Пришли <b>одной строкой</b> адрес сайта или ленты (в т.ч. без https://) — "
            "постараюсь найти ленту новостей сам.\n"
            "• Привязка к каналу пока делается через номер источника новостей и номер канала "
            "(добавим отдельные кнопки следующим шагом)."
        )
    lines: list[str] = ["<b>Источники новостей</b>", ""]
    for r in rows:
        st = "✅" if r["enabled"] else "⏸"
        title = escape(str(r["feed_title"] or "—"))
        url = escape(str(r["url"]))
        ch = r.get("channel_id")
        ch_title = r.get("channel_title")
        if ch:
            ch_line = f" → канал <b>#{ch}</b> {escape(str(ch_title or ''))}"
        else:
            ch_line = " → <i>канал не привязан</i>"
        lines.append(
            f"{st} <b>#{r['id']}</b> {title}\n<code>{url}</code>{ch_line}\n"
        )
    lines.append("")
    lines.append("Чтобы добавить источник новостей, пришли ссылку на сайт одной строкой.")
    return "\n".join(lines)


async def render_channels_html(user_id: int, bot: Bot) -> str:
    rows = await list_channels(user_id)
    if not rows:
        return (
            "<b>Мои каналы</b>\n\n"
            "Пока пусто.\n\n"
            "Добавление каналов кнопками будет в этом разделе.\n\n"
            "<i>Перед этим добавь бота админом канала с правом публикации.</i>"
        )

    lines: list[str] = ["<b>Мои каналы</b>", ""]
    for row in rows:
        chat_id = int(row["chat_id"])
        title = escape(str(row["title"] or "Без названия"))
        status = "⚪️"
        try:
            me = await bot.get_me()
            member = await bot.get_chat_member(chat_id=chat_id, user_id=me.id)
            can_post = bool(getattr(member, "can_post_messages", False))
            status = "✅" if can_post else "⚠️"
        except Exception:  # noqa: BLE001
            status = "❌"
        lines.append(f"{status} <b>#{row['id']}</b> {title}\n<code>{chat_id}</code>\n")

    lines.append("")
    lines.append("Проверка прав бота в канале обновляется автоматически.")
    return "\n".join(lines)


async def render_settings_html(user_id: int) -> str:
    ps = await get_posting_settings(user_id)
    daily = await get_daily_post_count(user_id)
    max_d = int(ps["max_posts_per_day"])
    on = "вкл" if ps["posting_enabled"] else "выкл"
    im = "да" if ps["send_images"] else "нет"
    qs, qe = ps["quiet_start_hour"], ps["quiet_end_hour"]
    if qs is None or qe is None:
        quiet_line = "выключены"
    else:
        quiet_line = f"{int(qs)}:00–{int(qe)}:00 (локальное время сервера)"
    return (
        "<b>Настройки постинга</b>\n\n"
        f"Автопост: <b>{escape(on)}</b>\n"
        f"Сегодня опубликовано: <b>{daily}</b> из <b>{max_d}</b> (лимит в сутки)\n"
        f"Тихие часы: {escape(quiet_line)}\n"
        f"Картинки из ленты новостей: <b>{escape(im)}</b>\n\n"
        "Управляй параметрами кнопками ниже."
    )


async def render_settings_kb(user_id: int):
    ps = await get_posting_settings(user_id)
    quiet_enabled = ps["quiet_start_hour"] is not None and ps["quiet_end_hour"] is not None
    return posting_settings_kb(
        posting_enabled=bool(ps["posting_enabled"]),
        send_images=bool(ps["send_images"]),
        quiet_enabled=bool(quiet_enabled),
    )


async def render_status_html(user_id: int) -> str:
    st = await get_user_stats(user_id)
    last = await get_last_event_for_user(user_id)
    if last:
        icon = "✅" if str(last["level"]) == "info" else "⚠️"
        last_line = (
            f"{icon} {escape(str(last['kind']))}: {escape(str(last['message']))} "
            f"(<code>{escape(str(last['created_at']))}</code>)"
        )
    else:
        last_line = "—"
    return (
        "<b>Статус</b>\n\n"
        f"Каналов: <b>{st['channels']}</b>\n"
        f"Источников новостей: <b>{st['sources']}</b>\n"
        f"Привязано к каналам: <b>{st['linked_sources']}</b>\n"
        f"Уже опубликовано записей: <b>{st['posted_entries']}</b>\n\n"
        f"Последнее событие: {last_line}"
    )


async def cmd_start(message: Message) -> None:
    if message.from_user:
        await ensure_user(message.from_user.id)
    settings = load_settings()
    name = (message.from_user.full_name if message.from_user else "друг").strip()
    key_hint = ""
    if not settings.openai_api_key:
        key_hint = (
            "\n\n⚠️ Для ответов в чате добавь в `.env` ключ `OPENAI_API_KEY=...` "
            "и перезапусти бота."
        )
    await message.answer(
        main_menu_text(name, key_hint=key_hint),
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )


async def add_channel_from_raw(message: Message, bot: Bot, raw: str) -> None:
    if not message.from_user:
        return
    await ensure_user(message.from_user.id)
    raw = raw.strip()
    if not raw:
        await message.answer(
            "Пришли ссылку на канал или его числовой id.\n"
            "Пример: <code>https://t.me/username</code>",
            parse_mode="HTML",
        )
        return

    chat_ref: int | str
    try:
        chat_ref = int(raw)
    except ValueError:
        m = TG_LINK_RE.match(raw)
        if not m:
            await message.answer(
                "Формат не распознан. Пришли ссылку вида:\n"
                "<code>https://t.me/username</code>",
                parse_mode="HTML",
            )
            return
        chat_ref = f"@{m.group(1)}"

    status = await message.answer("Сохраняю канал…")
    title = None
    chat_id: int | None = None
    try:
        chat = await bot.get_chat(chat_ref)
        chat_id = int(chat.id)
        title = getattr(chat, "title", None)
    except Exception:  # noqa: BLE001
        if isinstance(chat_ref, int):
            # По числовому ID всё равно сохраняем; статус прав покажем в «Мои каналы».
            chat_id = chat_ref
        else:
            await status.edit_text(
                "Не могу открыть канал по ссылке/username.\n"
                "Проверь, что ссылка правильная и канал публичный.",
                parse_mode="HTML",
            )
            return

    if chat_id is None:
        await status.edit_text("Не удалось определить канал по ссылке.")
        return

    cid = await add_channel(message.from_user.id, chat_id=chat_id, title=title)
    await status.edit_text(
        f"Канал добавлен: <b>#{cid}</b> {escape(str(title or 'Без названия'))}\n"
        f"<code>{chat_id}</code>\n\n"
        "Проверка прав бота отображается в разделе «Мои каналы».",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


async def run_add_feed_pipeline(message: Message, status: Message, raw: str) -> None:
    if not message.from_user:
        return
    await ensure_user(message.from_user.id)
    raw = raw.strip()
    await status.edit_text("Ищу ленту…")
    try:
        preview = await asyncio.wait_for(resolve_to_feed_preview(raw), timeout=75.0)
    except asyncio.TimeoutError:
        await status.edit_text(
            "Слишком долго жду ответа сайта. Попробуй прямую ссылку на ленту "
            "(часто это …/feed/ или …/rss) или повтори позже.",
            parse_mode="HTML",
        )
        return
    except ValueError as exc:
        await status.edit_text(f"Не получилось: {escape(str(exc))}", parse_mode="HTML")
        return
    except Exception as exc:  # noqa: BLE001
        logging.exception("Feed resolve failed")
        await status.edit_text(
            f"Ошибка сети или сервера: <code>{escape(type(exc).__name__)}</code>",
            parse_mode="HTML",
        )
        return

    try:
        sid = await add_rss_source(
            message.from_user.id,
            url=preview.url,
            feed_title=preview.title,
        )
    except aiosqlite.IntegrityError:
        await status.edit_text("Такой URL уже есть в твоём списке.")
        return

    sample_lines = "\n".join(
        f"• {escape(t)}"
        for t, _ in preview.sample_entries[:3]
    )
    await status.edit_text(
        f"Добавлено <b>#{sid}</b>: {escape(preview.title)}\n\n"
        f"Лента новостей: <code>{escape(preview.url)}</code>\n\n"
        f"Примеры записей:\n{sample_lines}",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


async def message_plain_url_as_source(message: Message) -> None:
    """Одна строка https://… — попытка добавить источник новостей (раньше ответа ИИ)."""
    if not message.from_user or not message.text:
        return
    await ensure_user(message.from_user.id)
    raw = message.text.strip()
    status = await message.answer("Ищу ленту…")
    await run_add_feed_pipeline(message, status, raw)


async def handle_pending_action_input(message: Message, bot: Bot) -> bool:
    if not message.from_user or not message.text:
        return False
    user_id = message.from_user.id
    action = pending_action_by_user.get(user_id)
    if not action:
        return False

    raw = message.text.strip()

    if action == "add_channel":
        pending_action_by_user.pop(user_id, None)
        await add_channel_from_raw(message, bot, raw)
        return True

    if action == "add_source":
        pending_action_by_user.pop(user_id, None)
        status = await message.answer("Ищу ленту…")
        await run_add_feed_pipeline(message, status, raw)
        return True

    if action == "del_channel":
        if not raw.isdigit():
            await message.answer("Нужен номер канала из списка, например: 2")
            return True
        pending_action_by_user.pop(user_id, None)
        ok = await delete_channel(user_id, int(raw))
        await message.answer("Канал удалён." if ok else "Не нашёл такой номер или канал не твой.")
        return True

    if action == "del_source":
        if not raw.isdigit():
            await message.answer("Нужен номер источника новостей из списка, например: 3")
            return True
        pending_action_by_user.pop(user_id, None)
        sid = int(raw)
        ok = await delete_rss_source(user_id, sid)
        await message.answer(
            f"Источник новостей #{sid} удалён." if ok else "Не нашёл такой номер или он не твой."
        )
        return True

    if action == "link_source":
        parts = raw.split()
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            await message.answer(
                "Нужно два номера: сначала источник новостей, потом канал. Пример: 4 2"
            )
            return True
        pending_action_by_user.pop(user_id, None)
        rss_id, ch_id = int(parts[0]), int(parts[1])
        ok = await set_rss_source_channel(user_id, rss_id=rss_id, channel_id=ch_id)
        await message.answer(
            f"Готово: источник новостей #{rss_id} → канал #{ch_id}."
            if ok
            else "Не вышло — проверь номера # в списках и что канал твой."
        )
        return True

    if action == "post_once":
        if not raw.isdigit():
            await message.answer("Нужен номер источника новостей из списка, например: 1")
            return True
        pending_action_by_user.pop(user_id, None)
        settings = load_settings()
        if not settings.openai_api_key:
            await message.answer("Нужен ключ ИИ в `.env`: OPENAI_API_KEY")
            return True
        jid = await get_feed_job_for_user(user_id, int(raw))
        if not jid:
            await message.answer("Источник новостей не найден, не привязан к каналу или выключен.")
            return True
        status = await message.answer("Публикую одну запись…")
        posted = await process_one_feed_job(bot, settings, jid, ignore_user_posting_rules=True)
        await status.edit_text("Готово — проверь канал." if posted else "Новых записей нет или лента пуста.")
        return True

    return False


async def ai_reply(message: Message, bot: Bot) -> None:
    if not message.text or not message.text.strip():
        return
    settings = load_settings()
    if not settings.openai_api_key:
        await message.answer(
            "Ключ ИИ не настроен. Добавь в `.env` строку:\n\n"
            "`OPENAI_API_KEY=sk-...`\n\n"
            "Перезапусти бота и открой главное меню кнопкой."
        )
        return

    text = message.text.strip()
    if len(text) > 12000:
        await message.answer("Слишком длинное сообщение. Разбей на части или сократи.")
        return

    await bot.send_chat_action(message.chat.id, "typing")
    try:
        answer = await complete_chat(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            user_text=text,
        )
    except Exception as exc:  # noqa: BLE001
        logging.exception("AI request failed")
        await message.answer(
            "Не удалось получить ответ от ИИ. Проверь ключ, баланс API и модель.\n"
            f"Детали: `{type(exc).__name__}`",
            parse_mode="Markdown",
        )
        return

    chunks = [c for c in split_for_telegram(answer) if c]
    for i, chunk in enumerate(chunks):
        await message.answer(
            chunk,
            reply_markup=main_menu_kb() if i == len(chunks) - 1 else None,
        )


async def on_text_message(message: Message, bot: Bot) -> None:
    if not message.text:
        return
    if await handle_pending_action_input(message, bot):
        return
    if looks_like_single_line_site_url(message.text):
        await message_plain_url_as_source(message)
        return
    await ai_reply(message, bot)


async def menu_router(callback: CallbackQuery) -> None:
    if not callback.data or not callback.message:
        return
    parts = callback.data.split(":", 1)
    if len(parts) < 2:
        await callback.answer()
        return
    action = parts[1]

    name = "друг"
    if callback.from_user and callback.from_user.full_name:
        name = callback.from_user.full_name.strip()
    key_hint = ""
    settings = load_settings()
    if not settings.openai_api_key:
        key_hint = (
            "\n\n⚠️ Для ответов в чате добавь в `.env` ключ `OPENAI_API_KEY=...` "
            "и перезапусти бота."
        )

    if action == "home":
        await callback.message.edit_text(
            main_menu_text(name, key_hint=key_hint),
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )
        await callback.answer()
        return

    if action == "channels":
        if not callback.from_user:
            await callback.answer()
            return
        await ensure_user(callback.from_user.id)
        html = await render_channels_html(callback.from_user.id, callback.bot)
        await callback.message.edit_text(html, parse_mode="HTML", reply_markup=channels_kb())
        await callback.answer()
        return

    if action == "sources":
        if not callback.from_user:
            await callback.answer()
            return
        await ensure_user(callback.from_user.id)
        html = await render_sources_html(callback.from_user.id)
        await callback.message.edit_text(
            html,
            parse_mode="HTML",
            reply_markup=sources_kb(),
        )
        await callback.answer()
        return

    if action == "status":
        if not callback.from_user:
            await callback.answer()
            return
        await ensure_user(callback.from_user.id)
        html = await render_status_html(callback.from_user.id)
        await callback.message.edit_text(
            html,
            parse_mode="HTML",
            reply_markup=back_to_main_kb(),
        )
        await callback.answer()
        return

    if action == "settings":
        if not callback.from_user:
            await callback.answer()
            return
        await ensure_user(callback.from_user.id)
        html = await render_settings_html(callback.from_user.id)
        kb = await render_settings_kb(callback.from_user.id)
        await callback.message.edit_text(
            html,
            parse_mode="HTML",
            reply_markup=kb,
        )
        await callback.answer()
        return

    if action == "drafts":
        await callback.message.edit_text(
            "**Черновики и очередь**\n\n"
            "Предпросмотр следующего материала, «опубликовать сейчас», «пропустить».\n\n"
            "_Раздел в разработке._",
            parse_mode="Markdown",
            reply_markup=back_to_main_kb(),
        )
        await callback.answer()
        return

    if action == "help":
        await callback.message.edit_text(
            "**Помощь**\n\n"
            "1. Создай канал в Telegram (или возьми существующий).\n"
            "2. Добавь этого бота **администратором** канала с правом **публиковать сообщения**.\n"
            "3. Возьми ссылку канала вида <code>https://t.me/your_channel</code>.\n"
            "4. **Источники новостей** удобно добавлять по ссылке на сайт: у многих СМИ есть "
            "лента раздела или главной страницы.\n\n"
            "Если что-то не работает — опиши в чате одним сообщением, постараюсь подсказать.\n\n"
            "Подробности и управление — через кнопки меню.",
            parse_mode="Markdown",
            reply_markup=back_to_main_kb(),
        )
        await callback.answer()
        return

    await callback.answer("Неизвестный раздел.")


async def channels_router(callback: CallbackQuery) -> None:
    if not callback.data or not callback.message or not callback.from_user:
        return
    await ensure_user(callback.from_user.id)
    action = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    if action == "add":
        pending_action_by_user[user_id] = "add_channel"
        await callback.answer()
        await callback.message.answer(
            "Пришли ссылку на канал или его numeric id одним сообщением.\n"
            "Пример: https://t.me/your_channel"
        )
        return
    if action == "del":
        pending_action_by_user[user_id] = "del_channel"
        await callback.answer()
        await callback.message.answer("Пришли номер канала # из списка в разделе «Мои каналы».")
        return
    await callback.answer()


async def sources_router(callback: CallbackQuery) -> None:
    if not callback.data or not callback.message or not callback.from_user:
        return
    await ensure_user(callback.from_user.id)
    action = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    if action == "add":
        pending_action_by_user[user_id] = "add_source"
        await callback.answer()
        await callback.message.answer(
            "Пришли одной строкой ссылку на сайт или прямую ссылку на ленту новостей."
        )
        return
    if action == "link":
        pending_action_by_user[user_id] = "link_source"
        await callback.answer()
        await callback.message.answer(
            "Пришли два номера через пробел: сначала источник новостей, потом канал.\n"
            "Пример: 4 2"
        )
        return
    if action == "del":
        pending_action_by_user[user_id] = "del_source"
        await callback.answer()
        await callback.message.answer(
            "Пришли номер источника новостей # из списка «Источники новостей»."
        )
        return
    if action == "post_once":
        pending_action_by_user[user_id] = "post_once"
        await callback.answer()
        await callback.message.answer(
            "Пришли номер источника новостей # для публикации одной записи."
        )
        return
    await callback.answer()


async def posting_settings_router(callback: CallbackQuery) -> None:
    if not callback.data or not callback.message or not callback.from_user:
        return
    await ensure_user(callback.from_user.id)
    parts = callback.data.split(":")
    if len(parts) < 2 or parts[0] != "ps":
        await callback.answer()
        return

    action = parts[1]
    user_id = callback.from_user.id

    if action == "toggle_posting":
        ps = await get_posting_settings(user_id)
        await update_posting_settings(user_id, posting_enabled=0 if ps["posting_enabled"] else 1)
        await callback.answer("Автопост обновлён")
    elif action == "toggle_images":
        ps = await get_posting_settings(user_id)
        await update_posting_settings(user_id, send_images=0 if ps["send_images"] else 1)
        await callback.answer("Настройка картинок обновлена")
    elif action == "max" and len(parts) == 3 and parts[2].isdigit():
        n = int(parts[2])
        if 1 <= n <= 500:
            await update_posting_settings(user_id, max_posts_per_day=n)
            await callback.answer(f"Лимит: {n}/день")
        else:
            await callback.answer("Недопустимый лимит")
            return
    elif action == "toggle_quiet":
        ps = await get_posting_settings(user_id)
        quiet_on = ps["quiet_start_hour"] is not None and ps["quiet_end_hour"] is not None
        if quiet_on:
            await update_posting_settings(user_id, quiet_start_hour=None, quiet_end_hour=None)
            await callback.answer("Тихие часы выключены")
        else:
            await update_posting_settings(user_id, quiet_start_hour=22, quiet_end_hour=8)
            await callback.answer("Тихие часы: 22:00-08:00")
    elif action == "quiet" and len(parts) == 4 and parts[2].isdigit() and parts[3].isdigit():
        a, b = int(parts[2]), int(parts[3])
        if 0 <= a <= 23 and 0 <= b <= 23:
            await update_posting_settings(user_id, quiet_start_hour=a, quiet_end_hour=b)
            await callback.answer(f"Тихие часы: {a}:00-{b}:00")
        else:
            await callback.answer("Часы должны быть 0..23")
            return
    elif action == "refresh":
        await callback.answer("Обновлено")
    else:
        await callback.answer()
        return

    html = await render_settings_html(user_id)
    kb = await render_settings_kb(user_id)
    await callback.message.edit_text(
        html,
        parse_mode="HTML",
        reply_markup=kb,
    )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    settings = load_settings()
    await init_db()

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    asyncio.create_task(run_post_worker_loop(bot))

    dp.message.register(cmd_start, CommandStart())
    dp.callback_query.register(menu_router, F.data.startswith("menu:"))
    dp.callback_query.register(channels_router, F.data.startswith("ch:"))
    dp.callback_query.register(sources_router, F.data.startswith("src:"))
    dp.callback_query.register(posting_settings_router, F.data.startswith("ps:"))
    dp.message.register(on_text_message, F.text & ~F.text.startswith("/"))

    # Иначе Telegram отдаёт Conflict, если у бота остался webhook или второй процесс polling.
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
