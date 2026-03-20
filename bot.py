from __future__ import annotations

import asyncio
import logging
import re
from html import escape

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject, CommandStart
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
    get_feed_job_for_user,
    get_last_event_for_user,
    get_user_stats,
    init_db,
    list_channels,
    list_rss_sources,
    set_rss_source_channel,
)
from feed_discovery import resolve_to_feed_preview
from keyboards import back_to_main_kb, main_menu_kb
from post_worker import process_one_feed_job, run_post_worker_loop

URL_ONE_LINE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)
TG_LINK_RE = re.compile(r"^(?:https?://)?(?:t\.me/|telegram\.me/)?@?([A-Za-z0-9_]{5,})/?$", re.IGNORECASE)


def main_menu_text(name: str, *, key_hint: str) -> str:
    return (
        f"Привет, {name}!\n\n"
        "Это бот **автопостинга в Telegram-каналы**: материалы из **твоих** источников "
        "(лучше всего RSS), пересказ на русском, пост без лишних ссылок и с одной картинкой.\n\n"
        "**Источник:** пришли в чат **одной строкой** ссылку на **сайт** (https://…) — бот "
        "попробует найти ленту сам. Или выбери раздел «Мои источники».\n\n"
        "Другой вопрос по боту — просто напиши текстом (не одной только ссылкой)."
        f"{key_hint}"
    )


async def render_sources_html(user_id: int) -> str:
    rows = await list_rss_sources(user_id)
    if not rows:
        return (
            "<b>Мои источники информации</b>\n\n"
            "Пока пусто.\n\n"
            "• Пришли <b>одной строкой</b> ссылку на <b>сайт</b> (https://…) — постараюсь "
            "найти RSS сам.\n"
            "• Или укажи ленту явно: <code>/add_rss https://…/feed.xml</code>\n"
            "• Привяжи ленту к каналу: <code>/link_rss N M</code> (номера из списков)"
        )
    lines: list[str] = ["<b>Мои источники информации</b>", ""]
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
    lines.append(
        "<code>/link_rss N M</code> — лента #N к каналу #M · "
        "одна строка https — добавить · <code>/del_rss N</code> · <code>/rss_list</code>"
    )
    return "\n".join(lines)


async def render_channels_html(user_id: int, bot: Bot) -> str:
    rows = await list_channels(user_id)
    if not rows:
        return (
            "<b>Мои каналы</b>\n\n"
            "Пока пусто.\n\n"
            "Добавь канал командой:\n"
            "<code>/add_channel {ссылка на канал}</code>\n\n"
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
    lines.append(
        "<code>/add_channel {ссылка}</code> · <code>/del_channel N</code> · <code>/channels</code>"
    )
    return "\n".join(lines)


async def render_status_html(user_id: int, settings) -> str:
    st = await get_user_stats(user_id)
    last = await get_last_event_for_user(user_id)
    ai_ok = bool(settings.openai_api_key)
    ai_line = "✅ ключ задан" if ai_ok else "❌ нет ключа — автопост и пересказ не работают"
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
        f"Источников RSS: <b>{st['sources']}</b>\n"
        f"Привязано к каналам: <b>{st['linked_sources']}</b>\n"
        f"Уже опубликовано записей: <b>{st['posted_entries']}</b>\n\n"
        f"ИИ: {ai_line}\n"
        f"Интервал опроса RSS: <code>{settings.poll_interval_sec}</code> с "
        "(<code>POLL_INTERVAL_SEC</code> в .env)\n\n"
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


async def cmd_help(message: Message) -> None:
    if message.from_user:
        await ensure_user(message.from_user.id)
    await message.answer(
        "**Команды**\n"
        "/start — главное меню\n"
        "/help — эта справка\n"
        "/add_channel `{ссылка на канал}` — добавить канал\n"
        "/channels — список каналов\n"
        "/del_channel `N` — удалить канал по номеру\n"
        "/link_rss `N` `M` — привязать ленту #N к каналу #M\n"
        "/post_once `N` — выложить одну новую запись из ленты #N в канал\n"
        "/status — сводка по твоему аккаунту\n"
        "/health — быстрая диагностика бота\n"
        "Ссылка на сайт одной строкой (https://…) — найти ленту и добавить\n"
        "/add_rss `URL` — добавить RSS/Atom вручную\n"
        "/rss_list — список твоих лент\n"
        "/del_rss `N` — удалить источник по номеру\n\n"
        "**Меню**\n"
        "• *Мои каналы* — подключённые каналы и статус бота в них\n"
        "• *Мои источники* — RSS/ссылки, которые ты добавил\n"
        "• *Статус* — сводка и предупреждения\n"
        "• *Настройки постинга* — интервал, лимиты, картинки\n"
        "• *Черновики и очередь* — предпросмотр и публикация\n"
        "• *Помощь* — как подключить канал и RSS\n\n"
        "**ИИ:** в `.env` задай `OPENAI_API_KEY`, при необходимости "
        "`OPENAI_BASE_URL` и `OPENAI_MODEL`.",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )


async def cmd_add_channel(message: Message, command: CommandObject, bot: Bot) -> None:
    if not message.from_user:
        return
    await ensure_user(message.from_user.id)
    raw = (command.args or "").strip()
    if not raw:
        await message.answer(
            "Отправь команду в формате:\n"
            "<code>/add_channel {ссылка на канал}</code>\n\n"
            "Пример:\n"
            "<code>/add_channel https://t.me/juvejuv191</code>",
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
                "Формат не распознан. Используй:\n"
                "<code>/add_channel {ссылка на канал}</code>\n"
                "Например: <code>/add_channel https://t.me/username</code>",
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


async def cmd_channels(message: Message, bot: Bot) -> None:
    if not message.from_user:
        return
    await ensure_user(message.from_user.id)
    text = await render_channels_html(message.from_user.id, bot)
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_kb())


async def cmd_link_rss(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    await ensure_user(message.from_user.id)
    parts = (command.args or "").split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        await message.answer(
            "Команда: <code>/link_rss N M</code>\n"
            "N — номер источника в «Мои источники», M — номер канала в «Мои каналы».",
            parse_mode="HTML",
        )
        return
    rss_id, ch_id = int(parts[0]), int(parts[1])
    ok = await set_rss_source_channel(
        message.from_user.id,
        rss_id=rss_id,
        channel_id=ch_id,
    )
    if ok:
        await message.answer(
            f"Готово: источник #{rss_id} → канал #{ch_id}.",
            reply_markup=main_menu_kb(),
        )
    else:
        await message.answer(
            "Не вышло — проверь номера # в списках и что канал твой.",
        )


async def cmd_post_once(message: Message, command: CommandObject, bot: Bot) -> None:
    if not message.from_user:
        return
    await ensure_user(message.from_user.id)
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer(
            "Укажи номер источника: <code>/post_once 1</code>",
            parse_mode="HTML",
        )
        return
    settings = load_settings()
    if not settings.openai_api_key:
        await message.answer(
            "Нужен ключ ИИ в `.env`: <code>OPENAI_API_KEY</code>",
            parse_mode="HTML",
        )
        return
    jid = await get_feed_job_for_user(message.from_user.id, int(arg))
    if not jid:
        await message.answer(
            "Источник не найден, не привязан к каналу или выключен. "
            "Сначала <code>/link_rss N M</code>.",
            parse_mode="HTML",
        )
        return
    status = await message.answer("Публикую одну запись…")
    try:
        posted = await process_one_feed_job(bot, settings, jid)
    except Exception as exc:  # noqa: BLE001
        logging.exception("post_once failed")
        await status.edit_text(f"Ошибка: <code>{escape(type(exc).__name__)}</code>", parse_mode="HTML")
        return
    if posted:
        await status.edit_text("Готово — проверь канал.")
    else:
        await status.edit_text(
            "Новых записей нет (всё уже опубликовано) или лента пуста."
        )


async def cmd_status(message: Message) -> None:
    if not message.from_user:
        return
    await ensure_user(message.from_user.id)
    settings = load_settings()
    text = await render_status_html(message.from_user.id, settings)
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_kb())


async def cmd_health(message: Message, bot: Bot) -> None:
    """Короткая проверка здоровья: Telegram, БД, ключ ИИ."""
    checks: list[str] = []
    try:
        me = await bot.get_me()
        checks.append(f"Telegram API: ✅ @{escape(me.username or 'bot')}")
    except Exception as exc:  # noqa: BLE001
        checks.append(f"Telegram API: ❌ <code>{escape(type(exc).__name__)}</code>")

    try:
        st = await get_user_stats(message.from_user.id if message.from_user else 0)
        checks.append(
            f"БД SQLite: ✅ каналы={st['channels']}, источники={st['sources']}, опубликовано={st['posted_entries']}"
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(f"БД SQLite: ❌ <code>{escape(type(exc).__name__)}</code>")

    settings = load_settings()
    if settings.openai_api_key:
        checks.append("ИИ ключ: ✅ задан")
    else:
        checks.append("ИИ ключ: ❌ не задан")

    checks.append(f"Интервал воркера: <code>{settings.poll_interval_sec}</code> с")
    await message.answer("<b>Health Check</b>\n\n" + "\n".join(checks), parse_mode="HTML")


async def cmd_del_channel(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    await ensure_user(message.from_user.id)
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer("Укажи номер канала: <code>/del_channel 1</code>", parse_mode="HTML")
        return
    ok = await delete_channel(message.from_user.id, int(arg))
    if ok:
        await message.answer("Канал удалён.", reply_markup=main_menu_kb())
    else:
        await message.answer("Не нашёл такой номер или канал не твой.")


async def run_add_feed_pipeline(message: Message, status: Message, raw: str) -> None:
    if not message.from_user:
        return
    await ensure_user(message.from_user.id)
    raw = raw.strip()
    await status.edit_text("Ищу ленту…")
    try:
        preview = await resolve_to_feed_preview(raw)
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
        f"Лента: <code>{escape(preview.url)}</code>\n\n"
        f"Примеры записей:\n{sample_lines}",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


async def cmd_add_rss(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    raw = (command.args or "").strip()
    if not raw:
        await message.answer(
            "Укажи ссылку на сайт или на RSS, например:\n\n"
            "<code>/add_rss https://example.com</code>\n"
            "<code>/add_rss https://example.com/rss.xml</code>\n\n"
            "Или просто пришли ссылку на сайт <b>одной строкой</b> без команды.",
            parse_mode="HTML",
        )
        return

    status = await message.answer("Ищу ленту…")
    await run_add_feed_pipeline(message, status, raw)


async def message_plain_url_as_source(message: Message) -> None:
    """Одна строка https://… — считаем попыткой добавить источник (раньше ответа ИИ)."""
    if not message.from_user or not message.text:
        return
    await ensure_user(message.from_user.id)
    raw = message.text.strip()
    status = await message.answer("Ищу ленту…")
    await run_add_feed_pipeline(message, status, raw)


async def cmd_rss_list(message: Message) -> None:
    if not message.from_user:
        return
    await ensure_user(message.from_user.id)
    text = await render_sources_html(message.from_user.id)
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_kb())


async def cmd_del_rss(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    await ensure_user(message.from_user.id)
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer(
            "Укажи номер из списка, например: <code>/del_rss 2</code>",
            parse_mode="HTML",
        )
        return
    sid = int(arg)
    ok = await delete_rss_source(message.from_user.id, sid)
    if ok:
        await message.answer(
            f"Источник #{sid} удалён.",
            reply_markup=main_menu_kb(),
        )
    else:
        await message.answer("Не нашёл такой номер или он не твой.")


async def ai_reply(message: Message, bot: Bot) -> None:
    if not message.text or not message.text.strip():
        return
    settings = load_settings()
    if not settings.openai_api_key:
        await message.answer(
            "Ключ ИИ не настроен. Добавь в `.env` строку:\n\n"
            "`OPENAI_API_KEY=sk-...`\n\n"
            "Перезапусти бота или открой /start."
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
        await callback.message.edit_text(html, parse_mode="HTML", reply_markup=back_to_main_kb())
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
            reply_markup=back_to_main_kb(),
        )
        await callback.answer()
        return

    if action == "status":
        if not callback.from_user:
            await callback.answer()
            return
        await ensure_user(callback.from_user.id)
        html = await render_status_html(callback.from_user.id, settings)
        await callback.message.edit_text(
            html,
            parse_mode="HTML",
            reply_markup=back_to_main_kb(),
        )
        await callback.answer()
        return

    if action == "settings":
        await callback.message.edit_text(
            "**Настройки постинга**\n\n"
            "Интервал или лимит постов в сутки, тихие часы, политика картинки "
            "(с сайта / сгенерировать, если нет), текст без сторонних ссылок.\n\n"
            "_Раздел в разработке._",
            parse_mode="Markdown",
            reply_markup=back_to_main_kb(),
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
            "4. Источники лучше добавлять как **RSS**: у многих СМИ есть ссылка на ленту "
            "раздела или главной страницы.\n\n"
            "Если что-то не работает — опиши в чате одним сообщением, постараюсь подсказать.\n\n"
            "Команда /help — полная справка по меню.",
            parse_mode="Markdown",
            reply_markup=back_to_main_kb(),
        )
        await callback.answer()
        return

    await callback.answer("Неизвестный раздел.")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    settings = load_settings()
    await init_db()

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    asyncio.create_task(run_post_worker_loop(bot))

    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_help, Command("help"))
    dp.message.register(cmd_add_channel, Command("add_channel"))
    dp.message.register(cmd_channels, Command("channels"))
    dp.message.register(cmd_del_channel, Command("del_channel"))
    dp.message.register(cmd_link_rss, Command("link_rss"))
    dp.message.register(cmd_post_once, Command("post_once"))
    dp.message.register(cmd_status, Command("status"))
    dp.message.register(cmd_health, Command("health"))
    dp.message.register(cmd_add_rss, Command("add_rss"))
    dp.message.register(cmd_rss_list, Command("rss_list"))
    dp.message.register(cmd_del_rss, Command("del_rss"))
    dp.callback_query.register(menu_router, F.data.startswith("menu:"))
    dp.message.register(message_plain_url_as_source, F.text.regexp(URL_ONE_LINE))
    dp.message.register(ai_reply, F.text & ~F.text.startswith("/"))

    # Иначе Telegram отдаёт Conflict, если у бота остался webhook или второй процесс polling.
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
