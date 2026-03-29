from __future__ import annotations

import asyncio
import logging
import re
from html import escape

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
    ReplyKeyboardMarkup,
    URLInputFile,
)

from ai_service import complete_chat, split_for_telegram
from channel_permissions import bot_can_post_to_channel
from config import Settings, load_settings
from db import (
    add_channel,
    add_rss_source,
    delete_channel,
    delete_rss_source,
    ensure_user,
    get_daily_post_count,
    get_manual_publish_job,
    get_last_event_for_user,
    get_posting_settings,
    get_user_stats,
    init_db,
    is_duplicate_article_for_user,
    is_entry_posted,
    list_channels,
    list_rss_sources,
    mark_entry_posted,
    news_inbox_delete,
    news_inbox_delete_by_entry_key,
    news_inbox_get,
    news_inbox_list,
    news_inbox_newest,
    news_inbox_ordered_ids,
    update_posting_settings,
)
from drafts_helpers import DraftPublishSnapshot, get_draft_suggestion
from post_content import BuiltPost, build_feed_post_content
from feed_discovery import resolve_to_feed_preview
from football_feed_presets import FOOTBALL_PRESET_FEEDS
from rss_service import extract_feed_url_candidate, normalize_http_url
from keyboards import (
    channel_delete_pick_kb,
    channels_reply_kb,
    draft_channel_pick_kb,
    draft_detail_kb,
    inbox_channel_pick_kb,
    inbox_detail_kb,
    main_menu_reply_kb,
    news_inbox_empty_kb,
    news_inbox_list_kb,
    posting_settings_kb,
    publish_one_post_actions_kb,
    publish_one_post_channel_pick_kb,
    publish_one_post_empty_kb,
    publish_one_post_screen_kb,
    source_delete_pick_kb,
    sources_reply_kb,
)
from post_worker import process_one_feed_job, run_post_worker_loop
from rss_monitor import run_rss_monitor_loop
from rss_entries import FeedItem
from telegram_helpers import get_bot_user_id
from text_utils import sanitize_post_text

TG_LINK_RE = re.compile(r"^(?:https?://)?(?:t\.me/|telegram\.me/)?@?([A-Za-z0-9_]{5,})/?$", re.IGNORECASE)
pending_action_by_user: dict[int, str] = {}
# Снимок открытой новости (тот же материал при выборе канала и отправке, пока лента не сдвинулась).
draft_publish_target: dict[tuple[int, int], DraftPublishSnapshot] = {}
# Своё фото для публикации черновика (Telegram file_id) после «Изменить пост».
draft_channel_photo_override: dict[tuple[int, int], str] = {}
# Очередь «новые новости» (inbox_id из таблицы news_inbox).
inbox_publish_target: dict[tuple[int, int], DraftPublishSnapshot] = {}
inbox_channel_photo_override: dict[tuple[int, int], str] = {}
# «Опубликовать 1 пост»: job + своё фото (file_id), если пользователь нажал «Изменить».
post_once_pending: dict[int, dict[str, object]] = {}


async def _clear_previous_publish_one_preview(bot: Bot, user_id: int) -> None:
    p = post_once_pending.pop(user_id, None)
    if not p:
        return
    mid, cid = p.get("preview_message_id"), p.get("preview_chat_id")
    if isinstance(mid, int) and cid is not None:
        try:
            await bot.delete_message(chat_id=int(cid), message_id=mid)
        except TelegramBadRequest:
            pass


async def _send_publish_one_latest_preview(bot: Bot, chat_id: int, user_id: int) -> None:
    """Удаляет прежний предпросмотр (если был) и шлёт самую свежую новость из очереди."""
    row = await news_inbox_newest(user_id)
    await _clear_previous_publish_one_preview(bot, user_id)
    if not row:
        return
    inbox_id = int(row["id"])
    source_id = int(row["source_id"])
    html, _ignore_kb, preview_urls = await compose_inbox_detail(user_id, inbox_id)
    snap = inbox_publish_target.get((user_id, inbox_id))
    kb = publish_one_post_actions_kb(inbox_id)
    html_safe = _html_for_edit_message(html)
    post_plain = (snap.built.text if snap and snap.built else "") or ""
    st = load_settings()
    mx = min(st.post_max_images, len(preview_urls)) if preview_urls else 0
    urls = preview_urls[:mx] if preview_urls else []

    try:
        if (
            snap
            and snap.built
            and len(urls) == 1
            and _is_http_image_url(urls[0])
        ):
            cap = _preview_photo_caption(post_plain)
            photo = URLInputFile(url=urls[0])
            preview_msg = await bot.send_photo(
                chat_id,
                photo=photo,
                caption=cap[:1024],
                reply_markup=kb,
            )
            post_once_pending[user_id] = {
                "inbox_id": inbox_id,
                "source_id": source_id,
                "preview_message_id": preview_msg.message_id,
                "preview_chat_id": chat_id,
                "preview_kind": "photo",
                "override_photo_file_id": None,
            }
            return
    except Exception:  # noqa: BLE001
        logging.exception("Предпросмотр «Опубликовать 1 пост» (фото)")

    preview_msg = await bot.send_message(
        chat_id,
        html_safe,
        parse_mode="HTML",
        reply_markup=kb,
    )
    post_once_pending[user_id] = {
        "inbox_id": inbox_id,
        "source_id": source_id,
        "preview_message_id": preview_msg.message_id,
        "preview_chat_id": chat_id,
        "preview_kind": "text",
        "override_photo_file_id": None,
    }


class PostOnceStates(StatesGroup):
    """Редактирование предпросмотра «Опубликовать 1 пост» в исходном сообщении."""
    wait_edit_inbox = State()


class DraftEditStates(StatesGroup):
    wait_edit = State()


def _fallback_feed_title(norm_url: str) -> str:
    from urllib.parse import urlparse

    net = (urlparse(norm_url).netloc or "").split(":")[0]
    return f"{net or 'Сайт'} — лента не найдена автоматически"


def looks_like_single_line_site_url(text: str) -> bool:
    """Одна строка, похожая на URL сайта или ленты (в т.ч. Без https://)."""
    if not (text or "").strip() or len(text) > 4000:
        return False
    cand = extract_feed_url_candidate(text)
    if not cand:
        return False
    tl = cand.lower()
    # Ссылки на Telegram-каналы обрабатываются в «Мои каналы», не как лента новостей.
    if "t.me/" in tl or "telegram.me/" in tl:
        return False
    return True


async def _safe_edit_status(status: Message, text: str, **kwargs: object) -> None:
    """Telegram падает с «message is not modified», если текст совпал с предыдущим."""
    try:
        await status.edit_text(text, **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" in (getattr(e, "message", "") or str(e)).lower():
            return
        raise


async def _delete_message_safe(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


async def _replace_message_with_screen(
    message: Message,
    bot: Bot,
    text: str,
    *,
    parse_mode: str,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None = None,
) -> None:
    """Новое сообщение с текстом и клавиатурой (ReplyKeyboard нельзя прикрепить через edit)."""
    await _delete_message_safe(message)
    await bot.send_message(
        message.chat.id,
        text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
    )


async def _replace_callback_screen(
    callback: CallbackQuery,
    text: str,
    *,
    parse_mode: str,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None = None,
) -> None:
    if not callback.message or not callback.from_user:
        return
    await _delete_message_safe(callback.message)
    await callback.bot.send_message(
        callback.from_user.id,
        text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
    )


def main_menu_text(name: str, *, key_hint: str) -> str:
    posting_hint = (
        "\n\n**В канал** уходит только то, что ты отправишь сам: "
        "новые материалы копятся в очереди — **«Опубликовать 1 пост»** → "
        "предпросмотр → **«Куда отправить»** → канал."
    )
    return (
        f"Привет, {name}!\n\n"
        "Это бот **авто постинга в Telegram-каналы**: материалы из **твоих** источников новостей "
        "(через ленту сайта), пересказ на русском, пост без лишних ссылок и с одной картинкой.\n\n"
        "**Источник новостей:** пришли в чат **одной строкой** ссылку на **сайт** (https://…) — бот "
        "попробует найти ленту сам. Или открой раздел «Источники новостей».\n\n"
        "Другой вопрос по боту — просто напиши текстом (не одной только ссылкой)."
        f"{posting_hint}"
        f"{key_hint}"
    )


async def render_sources_html(user_id: int) -> str:
    rows = await list_rss_sources(user_id)
    if not rows:
        return (
            "<b>Источники новостей</b>\n\n"
            "Пока пусто.\n\n"
            "Пришли <b>одной строкой</b> адрес сайта или ленты (в т.ч. без https://) — "
            "постараюсь найти ленту новостей сам.\n\n"
            "Канал для публикации ты выбираешь отдельно в экране новости (кнопка «Куда отправить»)."
        )
    lines: list[str] = ["<b>Источники новостей</b>", ""]
    for r in rows:
        st = "✅" if r["enabled"] else "⏸"
        title = escape(str(r["feed_title"] or "—"))
        url = escape(str(r["url"]))
        lines.append(
            f"{st} <b>#{r['id']}</b> {title}\n<code>{url}</code>\n"
        )
    lines.append("")
    lines.append(
        "Канал для поста не привязывается к ленте: открой новость и выбери канал кнопкой "
        "<b>«Куда отправить»</b>."
    )
    lines.append("")
    lines.append(
        "Кнопка <b>«⚽ Футбольные ленты»</b> добавляет набор RSS: международные источники, "
        "русскоязычные СМИ, фан-сайты и региональные ленты (если такого URL ещё нет в списке)."
    )
    lines.append("")
    lines.append("Чтобы добавить свой сайт, пришли ссылку одной строкой.")
    return "\n".join(lines)


def _truncate_plain(s: str, n: int) -> str:
    t = (s or "").strip().replace("\n", " ")
    if len(t) <= n:
        return t
    return t[: n - 1] + "…"


def _enabled_sources(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [r for r in rows if r["enabled"]]


def _draft_channel_hint(_row: dict[str, object]) -> str:
    return "<i>Канал для отправки — кнопка «Куда отправить».</i>\n\n"


async def get_source_row(user_id: int, source_id: int) -> dict[str, object] | None:
    rows = await list_rss_sources(user_id)
    for r in rows:
        if int(r["id"]) == source_id:
            return r
    return None


def _inbox_time_label(row: dict[str, object]) -> str:
    pub = row.get("published_at")
    if isinstance(pub, str) and pub.strip():
        return f"опублик.: {pub[:19].replace('T', ' ')} UTC"
    disc = row.get("discovered_at")
    if isinstance(disc, str) and disc.strip():
        return f"в очереди с: {disc[:19]}"
    return "время не указано"


def _feed_item_from_inbox_row(row: dict[str, object]) -> FeedItem:
    img_raw = row.get("image_url")
    img = str(img_raw).strip() if img_raw else None
    pa = row.get("published_at")
    return FeedItem(
        entry_key=str(row.get("entry_key") or ""),
        title=str(row.get("title") or ""),
        body_text=str(row.get("body_text") or ""),
        link=str(row.get("link") or ""),
        image_url=img or None,
        published_at=str(pa).strip() if pa else None,
    )


async def render_news_inbox_html(user_id: int, *, heading: str = "Новости из лент") -> str:
    rows = await news_inbox_list(user_id)
    title = escape(heading)
    if not rows:
        return (
            f"<b>{title}</b>\n\n"
            "Очередь <b>новых новостей</b> пуста. Сюда попадают материалы, когда в одной из "
            "<b>включённых</b> лент обновляется верхняя запись (фоновый мониторинг RSS).\n\n"
            "Добавь или включи источники в разделе «Источники новостей»."
        )
    lines: list[str] = [
        f"<b>{title}</b>",
        "",
        "Список <b>всех новых</b> материалов: <b>сначала старые</b>, <b>ниже — новее</b> "
        "(дата из ленты, затем время в очереди). Самая свежая новость приходит "
        "<b>отдельным сообщением</b> ниже — там кнопки <b>«Изменить»</b>, "
        "<b>«Пропустить и удалить»</b> и <b>«Выставить»</b> (в канал).",
        "",
    ]
    for r in rows:
        iid = int(r["id"])
        sid = int(r["source_id"])
        name = escape(str(r.get("source_feed_title") or "—"))
        tit = escape(_truncate_plain(str(r.get("title") or "—"), 140))
        tlab = escape(_inbox_time_label(r))
        lines.append(
            f"📌 <b>#{iid}</b> · источник <b>#{sid}</b> {name}\n"
            f"<i>{tlab}</i>\n<b>{tit}</b>\n"
        )
    return "\n".join(lines)


def _html_for_edit_message(html: str, max_len: int = 4000) -> str:
    """Telegram: до 4096 символов на сообщение; запас под закрывающие теги."""
    if len(html) <= max_len:
        return html
    return html[: max_len - 40] + "\n\n<i>…текст обрезан (лимит Telegram)</i>"


def _is_http_image_url(url: str) -> bool:
    u = (url or "").strip()
    return u.startswith(("http://", "https://"))


def _preview_photo_caption(post_text_plain: str | None) -> str:
    """Подпись к превью-фото: тот же текст, что уйдёт в канал (лимит подписи Telegram 1024)."""
    t = (post_text_plain or "").strip()
    if not t:
        return "📷 Текст поста пока пуст — в канал уйдёт только картинка (или добавь текст в «Изменить»)."
    if len(t) <= 1024:
        return t
    return t[:1023] + "…"


async def _send_compose_preview_footers(
    message: Message,
    kb: InlineKeyboardMarkup,
    preview_urls: list[str],
    *,
    post_text_plain: str | None = None,
) -> None:
    """Фото-предпросмотр и/или строка с инлайн-кнопками под длинным текстом."""
    st = load_settings()
    mx = min(st.post_max_images, len(preview_urls)) if preview_urls else 0
    urls = preview_urls[:mx] if preview_urls else []
    cap = _preview_photo_caption(post_text_plain)
    try:
        if len(urls) == 1:
            u0 = urls[0]
            photo = URLInputFile(url=u0) if _is_http_image_url(u0) else u0
            await message.answer_photo(
                photo=photo,
                caption=cap,
                reply_markup=kb,
            )
        elif len(urls) > 1 and all(_is_http_image_url(u) for u in urls):
            media = [
                InputMediaPhoto(
                    media=URLInputFile(url=urls[0]),
                    caption=cap[:1024],
                ),
                *(InputMediaPhoto(media=URLInputFile(url=u)) for u in urls[1:]),
            ]
            await message.answer_media_group(media=media)
        elif len(urls) > 1:
            u0 = urls[0]
            photo0 = URLInputFile(url=u0) if _is_http_image_url(u0) else u0
            await message.answer_photo(photo=photo0, caption=cap, reply_markup=kb)
            await message.answer(
                "👇 <b>Действия с черновиком</b>",
                parse_mode="HTML",
                reply_markup=kb,
            )
        elif not urls:
            await message.answer(
                "👇 Действия с постом — кнопки ниже.",
                parse_mode="HTML",
                reply_markup=kb,
            )
    except Exception:
        logging.exception("Предпросмотр фото черновика")


async def compose_draft_detail(
    user_id: int, source_id: int
) -> tuple[str, InlineKeyboardMarkup, list[str]]:
    """Текст черновика, клавиатура и URL предпросмотр, а фото; одна выборка ленты на экран."""
    row = await get_source_row(user_id, source_id)
    if not row:
        return "<b>Черновик</b>\n\nИсточник не найден.", draft_detail_kb(source_id, can_skip=False), []
    if not row["enabled"]:
        return (
            "<b>Черновик</b>\n\nИсточник выключен. Включи его в списке источников.",
            draft_detail_kb(source_id, can_skip=False),
            [],
        )
    hint = _draft_channel_hint(row)
    sug = await get_draft_suggestion(user_id, source_id, str(row["url"]))
    name = escape(str(row.get("feed_title") or "—"))
    if not sug:
        html = (
            f"<b>Черновик</b> · источник <b>#{source_id}</b> {name}\n"
            f"{hint}"
            f"<i>Лента пуста или недоступна.</i>"
        )
        return html, draft_detail_kb(source_id, can_skip=False), []
    link = escape(sug.item.link) if sug.item.link else "—"
    if sug.kind == "repeat":
        note = (
            "<i>Все свежие записи в ленте уже отмечены как обработанные. "
            "Ниже — последняя сверху; можно снова отправить с пересказом.</i>\n\n"
        )
    else:
        note = ""

    settings = load_settings()
    ps = await get_posting_settings(user_id)
    try:
        built = await build_feed_post_content(
            sug.item,
            settings,
            send_images=bool(ps["send_images"]),
            polish_english=settings.post_polish_english_to_russian,
        )
        preview_urls = list(built.image_urls)
    except Exception as exc:
        logging.exception("Черновик: не удалось собрать готовый пост")
        title = escape(sug.item.title)
        body = escape(_truncate_plain(sug.item.body_text, 3500))
        err = escape(str(exc)[:400])
        html = (
            f"<b>Черновик</b> · <b>#{source_id}</b> {name}\n"
            f"{hint}"
            f"{note}"
            f"<i>Не удалось подготовить пересказ:</i> {err}\n\n"
            f"<b>{title}</b>\n\n{body}\n\n"
            f"Ссылка: <code>{link}</code>"
        )
        draft_publish_target[(user_id, source_id)] = DraftPublishSnapshot(
            item=sug.item,
            kind=sug.kind,
            built=None,
        )
        return html, draft_detail_kb(source_id, can_skip=(sug.kind == "new")), []

    content_esc = escape(_truncate_plain(built.text, 3800))
    tail = "…" if len(built.text) > 3800 else ""
    feed_title_esc = escape(_truncate_plain(sug.item.title, 240))
    html = (
        f"<b>Готовый черновик</b> · <b>#{source_id}</b> {name}\n"
        f"{hint}"
        f"{note}"
        f"<i>Заголовок в ленте:</i> {feed_title_esc}\n\n"
        f"{content_esc}{tail}\n\n"
        f"<i>Фото: {len(built.image_urls)} шт.</i>\n"
        f"Ссылка: <code>{link}</code>"
    )
    draft_publish_target[(user_id, source_id)] = DraftPublishSnapshot(
        item=sug.item,
        kind=sug.kind,
        built=built,
    )
    kb = draft_detail_kb(
        source_id,
        can_skip=(sug.kind == "new"),
    )
    return html, kb, preview_urls


async def compose_inbox_detail(
    user_id: int, inbox_id: int
) -> tuple[str, InlineKeyboardMarkup, list[str]]:
    """Как черновик, но из строки очереди news_inbox (без повторного парса ленты для текста записи)."""
    row = await news_inbox_get(user_id, inbox_id)
    if not row:
        return "<b>Новость</b>\n\nЗапись не найдена.", inbox_detail_kb(inbox_id), []
    source_id = int(row["source_id"])
    src_row = await get_source_row(user_id, source_id)
    name = escape(str(row.get("source_feed_title") or "—"))
    hint = _draft_channel_hint(src_row) if src_row else ""
    if not src_row:
        html = (
            f"<b>Новость</b> · <b>#{inbox_id}</b>\n"
            f"{hint}"
            f"<i>Источник удалён или недоступен.</i>"
        )
        return html, inbox_detail_kb(inbox_id), []

    if not src_row["enabled"]:
        hint_off = (
            "<i>Источник выключен — включи его в списке источников, чтобы отправить пост в канал.</i>\n\n"
        )
    else:
        hint_off = ""

    item = _feed_item_from_inbox_row(row)
    link = escape(item.link) if item.link else "—"
    tlab = escape(_inbox_time_label(row))

    settings = load_settings()
    ps = await get_posting_settings(user_id)
    try:
        built = await build_feed_post_content(
            item,
            settings,
            send_images=bool(ps["send_images"]),
            polish_english=settings.post_polish_english_to_russian,
        )
        preview_urls = list(built.image_urls)
    except Exception as exc:
        logging.exception("Очередь новостей: не удалось собрать готовый пост")
        title = escape(item.title)
        body = escape(_truncate_plain(item.body_text, 3500))
        err = escape(str(exc)[:400])
        html = (
            f"<b>Черновик из очереди</b> · <b>#{inbox_id}</b> · источник <b>#{source_id}</b> {name}\n"
            f"{hint_off}{hint}"
            f"<i>Время:</i> {tlab}\n"
            f"<i>Не удалось подготовить пересказ:</i> {err}\n\n"
            f"<b>{title}</b>\n\n{body}\n\n"
            f"Ссылка: <code>{link}</code>"
        )
        inbox_publish_target[(user_id, inbox_id)] = DraftPublishSnapshot(
            item=item,
            kind="new",
            built=None,
        )
        return html, inbox_detail_kb(inbox_id), []

    content_esc = escape(_truncate_plain(built.text, 3800))
    tail = "…" if len(built.text) > 3800 else ""
    feed_title_esc = escape(_truncate_plain(item.title, 240))
    html = (
        f"<b>Готовый черновик</b> · <b>#{inbox_id}</b> · источник <b>#{source_id}</b> {name}\n"
        f"{hint_off}{hint}"
        f"<i>Время:</i> {tlab}\n"
        f"<i>Заголовок в ленте:</i> {feed_title_esc}\n\n"
        f"{content_esc}{tail}\n\n"
        f"<i>Фото: {len(built.image_urls)} шт.</i>\n"
        f"Ссылка: <code>{link}</code>"
    )
    inbox_publish_target[(user_id, inbox_id)] = DraftPublishSnapshot(
        item=item,
        kind="new",
        built=built,
    )
    return html, inbox_detail_kb(inbox_id), preview_urls


async def render_stored_draft_detail(
    user_id: int, source_id: int,
) -> tuple[str, InlineKeyboardMarkup, list[str]] | None:
    """Текст черновика из уже открытого снимка (без перечитывания ленты) — после ручного «Изменить пост»."""
    snap = draft_publish_target.get((user_id, source_id))
    if not snap:
        return None
    row = await get_source_row(user_id, source_id)
    if not row:
        return None
    hint = _draft_channel_hint(row)
    name = escape(str(row.get("feed_title") or "—"))
    link = escape(snap.item.link) if snap.item.link else "—"
    if snap.kind == "repeat":
        note = (
            "<i>Все свежие записи в ленте уже отмечены. "
            "Ниже — последняя сверху; можно снова отправить с пересказом.</i>\n\n"
        )
    else:
        note = ""
    if not snap.built:
        title = escape(snap.item.title)
        body = escape(_truncate_plain(snap.item.body_text, 3500))
        html = (
            f"<b>Черновик</b> · <b>#{source_id}</b> {name}\n"
            f"{hint}"
            f"{note}"
            f"<b>{title}</b>\n\n{body}\n\n"
            f"Ссылка: <code>{link}</code>"
        )
        return html, draft_detail_kb(source_id, can_skip=(snap.kind == "new")), []
    content_esc = escape(_truncate_plain(snap.built.text, 3800))
    tail = "…" if len(snap.built.text) > 3800 else ""
    feed_title_esc = escape(_truncate_plain(snap.item.title, 240))
    html = (
        f"<b>Готовый черновик</b> · <b>#{source_id}</b> {name}\n"
        f"{hint}"
        f"{note}"
        f"<i>Заголовок в ленте:</i> {feed_title_esc}\n\n"
        f"{content_esc}{tail}\n\n"
        f"<i>Фото: {len(snap.built.image_urls)} шт.</i>\n"
        f"Ссылка: <code>{link}</code>"
    )
    kb = draft_detail_kb(source_id, can_skip=(snap.kind == "new"))
    return html, kb, list(snap.built.image_urls)


async def render_stored_inbox_detail(
    user_id: int, inbox_id: int,
) -> tuple[str, InlineKeyboardMarkup, list[str]] | None:
    snap = inbox_publish_target.get((user_id, inbox_id))
    if not snap:
        return None
    row = await news_inbox_get(user_id, inbox_id)
    if not row:
        return None
    source_id = int(row["source_id"])
    src_row = await get_source_row(user_id, source_id)
    name = escape(str(row.get("source_feed_title") or "—"))
    hint = _draft_channel_hint(src_row) if src_row else ""
    link = escape(snap.item.link) if snap.item.link else "—"
    tlab = escape(_inbox_time_label(row))
    hint_off = ""
    if src_row and not src_row["enabled"]:
        hint_off = (
            "<i>Источник выключен — включи его в списке источников, чтобы отправить пост в канал.</i>\n\n"
        )
    if not snap.built:
        title = escape(snap.item.title)
        body = escape(_truncate_plain(snap.item.body_text, 3500))
        html = (
            f"<b>Черновик из очереди</b> · <b>#{inbox_id}</b> · источник <b>#{source_id}</b> {name}\n"
            f"{hint_off}{hint}"
            f"<i>Время:</i> {tlab}\n"
            f"<b>{title}</b>\n\n{body}\n\n"
            f"Ссылка: <code>{link}</code>"
        )
        return html, inbox_detail_kb(inbox_id), []
    content_esc = escape(_truncate_plain(snap.built.text, 3800))
    tail = "…" if len(snap.built.text) > 3800 else ""
    feed_title_esc = escape(_truncate_plain(snap.item.title, 240))
    html = (
        f"<b>Готовый черновик</b> · <b>#{inbox_id}</b> · источник <b>#{source_id}</b> {name}\n"
        f"{hint_off}{hint}"
        f"<i>Время:</i> {tlab}\n"
        f"<i>Заголовок в ленте:</i> {feed_title_esc}\n\n"
        f"{content_esc}{tail}\n\n"
        f"<i>Фото: {len(snap.built.image_urls)} шт.</i>\n"
        f"Ссылка: <code>{link}</code>"
    )
    return html, inbox_detail_kb(inbox_id), list(snap.built.image_urls)


async def _show_stored_draft_view_messages(message: Message, user_id: int, source_id: int) -> None:
    rendered = await render_stored_draft_detail(user_id, source_id)
    if not rendered:
        await message.answer("Не удалось показать черновик — открой его снова из списка.")
        return
    html, kb, preview_urls = rendered
    html_safe = _html_for_edit_message(html)
    await message.answer(html_safe, parse_mode="HTML", reply_markup=kb)
    snap_d = draft_publish_target.get((user_id, source_id))
    post_plain = (snap_d.built.text if snap_d and snap_d.built else "") or ""
    await _send_compose_preview_footers(message, kb, preview_urls, post_text_plain=post_plain)


async def _show_stored_inbox_view_messages(message: Message, user_id: int, inbox_id: int) -> None:
    rendered = await render_stored_inbox_detail(user_id, inbox_id)
    if not rendered:
        await message.answer("Не удалось показать новость — открой её снова из списка.")
        return
    html, kb, preview_urls = rendered
    html_safe = _html_for_edit_message(html)
    await message.answer(html_safe, parse_mode="HTML", reply_markup=kb)
    snap_d = inbox_publish_target.get((user_id, inbox_id))
    post_plain = (snap_d.built.text if snap_d and snap_d.built else "") or ""
    await _send_compose_preview_footers(message, kb, preview_urls, post_text_plain=post_plain)


async def _refresh_news_list_callback(callback: CallbackQuery, user_id: int) -> None:
    if not callback.message:
        return
    html = await render_news_inbox_html(user_id)
    rows = await news_inbox_list(user_id)
    rmk = news_inbox_list_kb(rows) if rows else news_inbox_empty_kb()
    await callback.message.edit_text(html, parse_mode="HTML", reply_markup=rmk)


async def _inbox_open_channel_picker(
    callback: CallbackQuery, user_id: int, inbox_id: int
) -> None:
    if not callback.message:
        return
    row = await news_inbox_get(user_id, inbox_id)
    if not row:
        await callback.answer("Запись уже удалена из очереди.", show_alert=True)
        return
    chs = await list_channels(user_id)
    if not chs:
        await callback.answer(
            "Сначала добавь канал в разделе «Мои 📺 каналы».",
            show_alert=True,
        )
        return
    source_id = int(row["source_id"])
    src = await get_source_row(user_id, source_id)
    if not src or not src["enabled"]:
        await callback.answer("Источник выключен или недоступен.", show_alert=True)
        return
    title = escape(str(row.get("source_feed_title") or "—"))
    await callback.message.edit_text(
        "<b>Выбери канал</b>\n\n"
        f"Новость <b>#{inbox_id}</b> · источник <b>#{source_id}</b> · {title}\n\n"
        "Куда отправить этот пост?",
        parse_mode="HTML",
        reply_markup=inbox_channel_pick_kb(inbox_id, chs),
    )
    await callback.answer()


async def _draft_open_channel_picker(
    callback: CallbackQuery, user_id: int, sid: int
) -> None:
    if not callback.message:
        return
    chs = await list_channels(user_id)
    if not chs:
        await callback.answer(
            "Сначала добавь канал в разделе «Мои 📺 каналы».",
            show_alert=True,
        )
        return
    row = await get_source_row(user_id, sid)
    if not row or not row["enabled"]:
        await callback.answer("Источник не найден или выключен.", show_alert=True)
        return
    title = escape(str(row.get("feed_title") or "—"))
    await callback.message.edit_text(
        "<b>Выбери канал</b>\n\n"
        f"Источник <b>#{sid}</b> · {title}\n\n"
        "Куда отправить этот пост?",
        parse_mode="HTML",
        reply_markup=draft_channel_pick_kb(sid, chs),
    )
    await callback.answer()


def _draft_source_ids_after_skip(linked: list[dict[str, object]], current_sid: int) -> list[int]:
    """После «Пропустить»: другие включённые источники по кругу, затем текущий."""
    ids = [int(r["id"]) for r in linked]
    if not ids:
        return []
    if current_sid not in ids:
        return ids
    i = ids.index(current_sid)
    others = ids[i + 1 :] + ids[:i]
    return others + [current_sid]


async def _show_draft_view(callback: CallbackQuery, user_id: int, source_id: int) -> bool:
    """Обновляет сообщение черновиком и превью фото. False — не удалось изменить текст сообщения."""
    html, kb, preview_urls = await compose_draft_detail(user_id, source_id)
    html_safe = _html_for_edit_message(html)
    try:
        await callback.message.edit_text(
            html_safe,
            parse_mode="HTML",
            reply_markup=kb,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in (getattr(exc, "message", "") or str(exc)).lower():
            return False
    snap_d = draft_publish_target.get((user_id, source_id))
    post_plain = (snap_d.built.text if snap_d and snap_d.built else "") or ""
    await _send_compose_preview_footers(
        callback.message,
        kb,
        preview_urls,
        post_text_plain=post_plain,
    )
    return True


async def _show_inbox_view(callback: CallbackQuery, user_id: int, inbox_id: int) -> bool:
    html, kb, preview_urls = await compose_inbox_detail(user_id, inbox_id)
    html_safe = _html_for_edit_message(html)
    if not callback.message:
        return False
    try:
        await callback.message.edit_text(
            html_safe,
            parse_mode="HTML",
            reply_markup=kb,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in (getattr(exc, "message", "") or str(exc)).lower():
            return False
    snap_d = inbox_publish_target.get((user_id, inbox_id))
    post_plain = (snap_d.built.text if snap_d and snap_d.built else "") or ""
    await _send_compose_preview_footers(
        callback.message,
        kb,
        preview_urls,
        post_text_plain=post_plain,
    )
    return True


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
    bot_uid = await get_bot_user_id(bot)
    for row in rows:
        chat_id = int(row["chat_id"])
        title = escape(str(row["title"] or "Без названия"))
        "⚪️"
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=bot_uid)
            can_post = bot_can_post_to_channel(member)
            status = "✅" if can_post else "⚠️"
        except Exception:  # noqa: BLE001
            status = "❌"
        lines.append(f"{status} <b>#{row['id']}</b> {title}\n<code>{chat_id}</code>\n")

    lines.append("")
    lines.append("Проверка прав бота в канале обновляется автоматически.")
    return "\n".join(lines)


async def render_settings_html(user_id: int) -> str:
    ps = await get_posting_settings(user_id)
    cfg = load_settings()
    daily = await get_daily_post_count(user_id)
    max_d = int(ps["max_posts_per_day"])
    if not cfg.allow_auto_posting:
        mode_ru = "ручной — черновик в боте, затем выбор канала «Куда отправить»"
    else:
        mode = str(ps.get("posting_mode") or ("auto" if ps["posting_enabled"] else "manual"))
        if mode == "auto":
            mode_ru = (
                "в настройках указан авто-режим, но публикация из RSS в канал отключена — "
                "только вручную: новость → «Куда отправить»"
            )
        else:
            mode_ru = "ручной — черновик в боте, затем «Куда отправить»"
    im = "да" if ps["send_images"] else "нет"
    qs, qe = ps["quiet_start_hour"], ps["quiet_end_hour"]
    if qs is None or qe is None:
        quiet_line = "выключены"
    else:
        quiet_line = f"{int(qs)}:00–{int(qe)}:00 (локальное время сервера)"
    return (
        "<b>Настройки постинга</b>\n\n"
        f"Режим: <b>{escape(mode_ru)}</b>\n"
        f"Сегодня опубликовано: <b>{daily}</b> из <b>{max_d}</b> (лимит в сутки; учитывается и при ручной отправке из очереди)\n"
        f"Тихие часы: {escape(quiet_line)}\n"
        f"Картинки к постам (лента + страница статьи): <b>{escape(im)}</b>\n\n"
        "Одинаковые новости по ссылке не дублируются между источниками.\n\n"
        "Управляй параметрами кнопками ниже."
    )


async def render_settings_kb(user_id: int):
    ps = await get_posting_settings(user_id)
    cfg = load_settings()
    quiet_enabled = ps["quiet_start_hour"] is not None and ps["quiet_end_hour"] is not None
    mode = str(ps.get("posting_mode") or ("auto" if ps["posting_enabled"] else "manual"))
    return posting_settings_kb(
        posting_mode=mode,
        send_images=bool(ps["send_images"]),
        quiet_enabled=bool(quiet_enabled),
        allow_auto_mode=cfg.allow_auto_posting,
    )


async def seed_football_preset_feeds(user_id: int) -> tuple[int, int]:
    """Добавляет пресетные ленты. Возвращает (число новых, число дубликатов по URL)."""
    added = 0
    skipped = 0
    for url, title in FOOTBALL_PRESET_FEEDS:
        try:
            norm = normalize_http_url(url)
        except ValueError:
            norm = (url or "").strip()
        if not norm:
            continue
        try:
            await add_rss_source(user_id, url=norm, feed_title=title)
            added += 1
        except aiosqlite.IntegrityError:
            skipped += 1
    return added, skipped


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
        f"Уже опубликовано записей: <b>{st['posted_entries']}</b>\n\n"
        "<i>Включённые ленты опрашиваются в фоне (уведомления о свежих записях); "
        "публикация в канал — только вручную из черновика.</i>\n\n"
        f"Последнее событие: {last_line}"
    )


async def cmd_start(message: Message) -> None:
    if message.from_user:
        await ensure_user(message.from_user.id)
        rows = await list_rss_sources(message.from_user.id)
        if not rows:
            n_new, n_skip = await seed_football_preset_feeds(message.from_user.id)
            if n_new:
                await message.answer(
                    f"⚽ Добавлено <b>{n_new}</b> RSS-лент по футболу по умолчанию "
                    f"(пропущено как уже есть: <b>{n_skip}</b>).\n\n"
                    "Дальше: открой <b>«Источники новостей»</b> или дождись уведомления о новой записи.",
                    parse_mode="HTML",
                )
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
        reply_markup=main_menu_reply_kb(),
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
    try:
        chat = await bot.get_chat(chat_ref)
        chat_id = int(chat.id)
        title = getattr(chat, "title", None)
    except Exception:  # noqa: BLE001
        if isinstance(chat_ref, int):
            # По-числовому ID всё равно сохраняем; статус прав покажем в «Мои каналы».
            chat_id = chat_ref
        else:
            await status.edit_text(
                "Не могу открыть канал по ссылке/username.\n"
                "Проверь, что ссылка правильная и канал публичный.",
                parse_mode="HTML",
            )
            return

    cid = await add_channel(message.from_user.id, chat_id=chat_id, title=title)
    await _replace_message_with_screen(
        status,
        bot,
        f"Канал добавлен: <b>#{cid}</b> {escape(str(title or 'Без названия'))}\n"
        f"<code>{chat_id}</code>\n\n"
        "Проверка прав бота отображается в разделе «Мои каналы».",
        parse_mode="HTML",
        reply_markup=main_menu_reply_kb(),
    )


async def run_add_feed_pipeline(message: Message, status: Message, raw: str) -> None:
    if not message.from_user:
        return
    await ensure_user(message.from_user.id)
    raw = raw.strip()
    # Не дублируем текст «Ищу ленту…» — иначе Telegram: message is not modified → падение.
    await _safe_edit_status(status, "Проверяю ленту новостей…")
    logging.info("feed add: user=%s url=%s", message.from_user.id, raw[:500])
    try:
        preview = await asyncio.wait_for(resolve_to_feed_preview(raw), timeout=75.0)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logging.info("feed resolve failed (%s), fallback add: %s", type(exc).__name__, raw[:200])
        try:
            norm = normalize_http_url(raw)
        except ValueError as ve:
            await _safe_edit_status(
                status,
                f"Не получилось: {escape(str(ve))}",
                parse_mode="HTML",
            )
            return
        try:
            sid = await add_rss_source(
                message.from_user.id,
                url=norm,
                feed_title=_fallback_feed_title(norm),
            )
        except aiosqlite.IntegrityError:
            await _safe_edit_status(status, "Такой URL уже есть в твоём списке.")
            return
        await _replace_message_with_screen(
            status,
            message.bot,
            (
                f"Источник <b>#{sid}</b> добавлен без проверки ленты.\n\n"
                f"Адрес: <code>{escape(norm)}</code>\n\n"
                "<i>Автоматически не удалось скачать RSS по этому URL "
                "(сайт не ответил, нет типовой ленты или нужна другая ссылка). "
                "Можно оставить как есть и позже прислать <b>прямую ссылку на .xml / rss</b> "
                "новым источником, либо удалить этот и добавить снова.</i>"
            ),
            parse_mode="HTML",
            reply_markup=main_menu_reply_kb(),
        )
        return

    try:
        sid = await add_rss_source(
            message.from_user.id,
            url=preview.url,
            feed_title=preview.title,
        )
    except aiosqlite.IntegrityError:
        await _safe_edit_status(status, "Такой URL уже есть в твоём списке.")
        return

    sample_lines = "\n".join(
        f"• {escape(t)}"
        for t, _ in preview.sample_entries[:3]
    )
    await _replace_message_with_screen(
        status,
        message.bot,
        f"Добавлено <b>#{sid}</b>: {escape(preview.title)}\n\n"
        f"Лента новостей: <code>{escape(preview.url)}</code>\n\n"
        f"Примеры записей:\n{sample_lines}",
        parse_mode="HTML",
        reply_markup=main_menu_reply_kb(),
    )


async def message_plain_url_as_source(message: Message) -> None:
    """Одна строка https://… — попытка добавить источник новостей (раньше ответа ИИ)."""
    if not message.from_user or not message.text:
        return
    await ensure_user(message.from_user.id)
    cand = extract_feed_url_candidate(message.text)
    if not cand:
        return
    status = await message.answer("Ищу ленту…")
    await run_add_feed_pipeline(message, status, cand)


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
        cand = extract_feed_url_candidate(raw) or raw.strip()
        status = await message.answer("Ищу ленту…")
        await run_add_feed_pipeline(message, status, cand)
        return True

    return False


async def handle_reply_menu_button(message: Message, bot: Bot) -> bool:
    """Те же действия, что у callback menu:/ch:/src:, но по тексту кнопок ReplyKeyboard."""
    if not message.from_user or not message.text:
        return False
    text = message.text.strip()
    user_id = message.from_user.id
    await ensure_user(user_id)

    settings = load_settings()
    name = (message.from_user.full_name or "друг").strip()
    key_hint = ""
    if not settings.openai_api_key:
        key_hint = (
            "\n\n⚠️ Для ответов в чате добавь в `.env` ключ `OPENAI_API_KEY=...` "
            "и перезапусти бота."
        )

    if text == "Мои 📺 каналы":
        html = await render_channels_html(user_id, bot)
        await message.answer(html, parse_mode="HTML", reply_markup=channels_reply_kb())
        return True
    if text == "📰 Источники новостей":
        html = await render_sources_html(user_id)
        await message.answer(html, parse_mode="HTML", reply_markup=sources_reply_kb())
        return True
    if text == "Помощь":
        await message.answer(
            "**Помощь**\n\n"
            "1. Создай канал в Telegram (или возьми существующий).\n"
            "2. Добавь этого бота **администратором** канала с правом **публиковать сообщения**.\n"
            "3. Возьми ссылку канала вида <code>https://t.me/your_channel</code>.\n"
            "4. **Источники новостей** удобно добавлять по ссылке на сайт: у многих СМИ есть "
            "лента раздела или главной страницы.\n\n"
            "Если что-то не работает — опиши в чате одним сообщением, постараюсь подсказать.\n\n"
            "Подробности и управление — через кнопки меню.",
            parse_mode="Markdown",
            reply_markup=main_menu_reply_kb(),
        )
        return True
    if text == "🏠 Главное меню":
        await message.answer(
            main_menu_text(name, key_hint=key_hint),
            parse_mode="Markdown",
            reply_markup=main_menu_reply_kb(),
        )
        return True

    if text == "➕ Добавить канал":
        pending_action_by_user[user_id] = "add_channel"
        await message.answer(
            "Пришли ссылку на канал или его numeric id одним сообщением.\n"
            "Пример: https://t.me/your_channel"
        )
        return True
    if text == "🗑 Удалить канал":
        rows = await list_channels(user_id)
        if not rows:
            await message.answer("Нет каналов в списке.")
            return True
        await message.answer(
            "<b>Удалить канал</b>\n\nВыбери канал:",
            parse_mode="HTML",
            reply_markup=channel_delete_pick_kb(rows),
        )
        return True
    if text == "🔄 Обновить список каналов":
        html = await render_channels_html(user_id, bot)
        await message.answer(html, parse_mode="HTML", reply_markup=channels_reply_kb())
        return True

    if text == "➕ Добавить источник новостей":
        pending_action_by_user[user_id] = "add_source"
        await message.answer(
            "Пришли одной строкой ссылку на сайт или прямую ссылку на ленту новостей."
        )
        return True
    if text == "⚽ Футбольные ленты (набор)":
        n_new, n_skip = await seed_football_preset_feeds(user_id)
        await message.answer(
            f"⚽ Добавлено новых лент: <b>{n_new}</b>. Уже в списке (тот же URL): <b>{n_skip}</b>.",
            parse_mode="HTML",
        )
        html = await render_sources_html(user_id)
        await message.answer(html, parse_mode="HTML", reply_markup=sources_reply_kb())
        return True
    if text == "🗑 Удалить источник новостей":
        rows = await list_rss_sources(user_id)
        if not rows:
            await message.answer("Нет источников")
            return True
        await message.answer(
            "<b>Удалить источник</b>\n\nВыбери из списка:",
            parse_mode="HTML",
            reply_markup=source_delete_pick_kb(rows),
        )
        return True
    if text == "📤 Опубликовать 1 пост":
        html = await render_news_inbox_html(user_id, heading="Опубликовать 1 пост")
        rows = await news_inbox_list(user_id)
        kb = publish_one_post_screen_kb() if rows else publish_one_post_empty_kb()
        await message.answer(html, parse_mode="HTML", reply_markup=kb)
        if rows:
            await _send_publish_one_latest_preview(bot, message.chat.id, user_id)
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
            reply_markup=main_menu_reply_kb() if i == len(chunks) - 1 else None,
        )


async def on_text_message(message: Message, bot: Bot) -> None:
    if not message.text:
        return
    if await handle_pending_action_input(message, bot):
        return
    if await handle_reply_menu_button(message, bot):
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
        await _replace_callback_screen(
            callback,
            main_menu_text(name, key_hint=key_hint),
            parse_mode="Markdown",
            reply_markup=main_menu_reply_kb(),
        )
        await callback.answer()
        return

    if action == "channels":
        if not callback.from_user:
            await callback.answer()
            return
        await ensure_user(callback.from_user.id)
        html = await render_channels_html(callback.from_user.id, callback.bot)
        await _replace_callback_screen(
            callback,
            html,
            parse_mode="HTML",
            reply_markup=channels_reply_kb(),
        )
        await callback.answer()
        return

    if action == "sources":
        if not callback.from_user:
            await callback.answer()
            return
        await ensure_user(callback.from_user.id)
        html = await render_sources_html(callback.from_user.id)
        await _replace_callback_screen(
            callback,
            html,
            parse_mode="HTML",
            reply_markup=sources_reply_kb(),
        )
        await callback.answer()
        return

    if action == "status":
        if not callback.from_user:
            await callback.answer()
            return
        await ensure_user(callback.from_user.id)
        html = await render_status_html(callback.from_user.id)
        await _replace_callback_screen(
            callback,
            html,
            parse_mode="HTML",
            reply_markup=main_menu_reply_kb(),
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
        if not callback.from_user:
            await callback.answer()
            return
        await ensure_user(callback.from_user.id)
        await _refresh_news_list_callback(callback, callback.from_user.id)
        await callback.answer()
        return

    if action == "help":
        await _replace_callback_screen(
            callback,
            "**Помощь**\n\n"
            "1. Создай канал в Telegram (или возьми существующий).\n"
            "2. Добавь этого бота **администратором** канала с правом **публиковать сообщения**.\n"
            "3. Возьми ссылку канала вида <code>https://t.me/your_channel</code>.\n"
            "4. **Источники новостей** удобно добавлять по ссылке на сайт: у многих СМИ есть "
            "лента раздела или главной страницы.\n\n"
            "Если что-то не работает — опиши в чате одним сообщением, постараюсь подсказать.\n\n"
            "Подробности и управление — через кнопки меню.",
            parse_mode="Markdown",
            reply_markup=main_menu_reply_kb(),
        )
        await callback.answer()
        return

    await callback.answer("Неизвестный раздел.")


async def channels_router(callback: CallbackQuery) -> None:
    if not callback.data or not callback.message or not callback.from_user:
        return
    await ensure_user(callback.from_user.id)
    user_id = callback.from_user.id
    parts = (callback.data or "").split(":")

    if len(parts) == 2 and parts[0] == "ch" and parts[1] == "add":
        pending_action_by_user[user_id] = "add_channel"
        await callback.answer()
        await callback.message.answer(
            "Пришли ссылку на канал или его numeric id одним сообщением.\n"
            "Пример: https://t.me/your_channel"
        )
        return

    if len(parts) == 2 and parts[0] == "ch" and parts[1] == "del":
        rows = await list_channels(user_id)
        if not rows:
            await callback.answer("Нет каналов в списке", show_alert=True)
            return
        await callback.message.edit_text(
            "<b>Удалить канал</b>\n\nВыбери канал:",
            parse_mode="HTML",
            reply_markup=channel_delete_pick_kb(rows),
        )
        await callback.answer()
        return

    if len(parts) == 3 and parts[0] == "ch" and parts[1] == "x" and parts[2].isdigit():
        cid = int(parts[2])
        ok = await delete_channel(user_id, cid)
        await callback.answer("Удалено" if ok else "Не вышло")
        html = await render_channels_html(user_id, callback.bot)
        await _replace_callback_screen(
            callback,
            html,
            parse_mode="HTML",
            reply_markup=channels_reply_kb(),
        )
        return

    await callback.answer()


async def sources_router(callback: CallbackQuery) -> None:
    if not callback.data or not callback.message or not callback.from_user:
        return
    await ensure_user(callback.from_user.id)
    user_id = callback.from_user.id
    parts = (callback.data or "").split(":", 1)
    if len(parts) < 2 or parts[0] != "src":
        await callback.answer()
        return
    action = parts[1]

    if action == "add":
        pending_action_by_user[user_id] = "add_source"
        await callback.answer()
        await callback.message.answer(
            "Пришли одной строкой ссылку на сайт или прямую ссылку на ленту новостей."
        )
        return

    if action == "football":
        n_new, n_skip = await seed_football_preset_feeds(user_id)
        await callback.answer(
            f"Новых лент: {n_new}. Уже были (тот же URL): {n_skip}.",
            show_alert=True,
        )
        html = await render_sources_html(user_id)
        await _replace_callback_screen(
            callback,
            html,
            parse_mode="HTML",
            reply_markup=sources_reply_kb(),
        )
        return

    if action == "del":
        rows = await list_rss_sources(user_id)
        if not rows:
            await callback.answer("Нет источников", show_alert=True)
            return
        await callback.message.edit_text(
            "<b>Удалить источник</b>\n\nВыбери из списка:",
            parse_mode="HTML",
            reply_markup=source_delete_pick_kb(rows),
        )
        await callback.answer()
        return

    if action == "post_once":
        html = await render_news_inbox_html(user_id, heading="Опубликовать 1 пост")
        rows = await news_inbox_list(user_id)
        kb = publish_one_post_screen_kb() if rows else publish_one_post_empty_kb()
        await callback.message.edit_text(html, parse_mode="HTML", reply_markup=kb)
        await callback.answer()
        if rows and callback.from_user:
            await _send_publish_one_latest_preview(
                callback.bot, callback.from_user.id, callback.from_user.id
            )
        return

    await callback.answer()


async def deprecated_link_callback(callback: CallbackQuery) -> None:
    """Старые кнопки l:s: / l:c: после отключения привязки лент к каналам."""
    if not callback.data or not callback.from_user:
        return
    await ensure_user(callback.from_user.id)
    await callback.answer(
        "Привязка лент к каналам больше не используется. "
        "Открой новость из очереди и нажми «Куда отправить».",
        show_alert=True,
    )


async def source_delete_router(callback: CallbackQuery) -> None:
    if not callback.data or not callback.message or not callback.from_user:
        return
    await ensure_user(callback.from_user.id)
    user_id = callback.from_user.id
    parts = (callback.data or "").split(":")
    if len(parts) != 2 or parts[0] != "sd" or not parts[1].isdigit():
        await callback.answer()
        return
    sid = int(parts[1])
    ok = await delete_rss_source(user_id, sid)
    await callback.answer("Удалено" if ok else "Не вышло")
    html = await render_sources_html(user_id)
    await _replace_callback_screen(
        callback,
        html,
        parse_mode="HTML",
        reply_markup=sources_reply_kb(),
    )


async def post_once_router(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data or not callback.from_user:
        return
    await ensure_user(callback.from_user.id)
    user_id = callback.from_user.id
    parts = (callback.data or "").split(":")

    if not parts or parts[0] != "po":
        await callback.answer()
        return

    if len(parts) == 2 and parts[1] == "chclose":
        if callback.message:
            try:
                await callback.message.delete()
            except TelegramBadRequest:
                pass
        await callback.answer()
        return

    if len(parts) == 3 and parts[1] == "editib" and parts[2].isdigit():
        inbox_id = int(parts[2])
        pend = post_once_pending.get(user_id)
        if not pend or int(pend.get("inbox_id", -1)) != inbox_id:
            await callback.answer("Открой снова «Опубликовать 1 пост».", show_alert=True)
            return
        await state.clear()
        await state.set_state(PostOnceStates.wait_edit_inbox)
        await state.update_data(
            inbox_id=inbox_id,
            target_chat_id=pend["preview_chat_id"],
            target_message_id=pend["preview_message_id"],
            preview_kind=pend.get("preview_kind") or "text",
        )
        await callback.answer()
        hint = (
            "✏️ Пришли **текст** одним сообщением — обновлю пост в сообщении с предпросмотром выше.\n"
            "Или **фото** с подписью (подпись = текст поста в канале).\n\n"
            "/cancel — отмена."
        )
        if callback.message:
            await callback.message.answer(hint, parse_mode="Markdown")
        else:
            await callback.bot.send_message(user_id, hint, parse_mode="Markdown")
        return

    if len(parts) == 3 and parts[1] == "skipib" and parts[2].isdigit():
        inbox_id = int(parts[2])
        pend = post_once_pending.get(user_id)
        if not pend or int(pend.get("inbox_id", -1)) != inbox_id:
            await callback.answer("Сессия устарела.", show_alert=True)
            return
        mids = pend.get("preview_message_id")
        cid = pend.get("preview_chat_id")
        await news_inbox_delete(user_id, inbox_id)
        inbox_publish_target.pop((user_id, inbox_id), None)
        inbox_channel_photo_override.pop((user_id, inbox_id), None)
        post_once_pending.pop(user_id, None)
        if isinstance(mids, int) and cid is not None:
            plain = "⏭ Запись пропущена и удалена из общего списка."
            try:
                await callback.bot.edit_message_text(
                    chat_id=int(cid),
                    message_id=mids,
                    text=plain,
                )
            except TelegramBadRequest:
                try:
                    await callback.bot.edit_message_caption(
                        chat_id=int(cid),
                        message_id=mids,
                        caption=plain[:1024],
                    )
                except TelegramBadRequest:
                    pass
        await callback.answer("Удалено из очереди")
        return

    if len(parts) == 3 and parts[1] == "pickib" and parts[2].isdigit():
        inbox_id = int(parts[2])
        row = await news_inbox_get(user_id, inbox_id)
        pend = post_once_pending.get(user_id)
        if not pend or int(pend.get("inbox_id", -1)) != inbox_id or not row:
            await callback.answer("Открой снова «Опубликовать 1 пост».", show_alert=True)
            return
        chs = await list_channels(user_id)
        if not chs:
            await callback.answer(
                "Сначала добавь канал в разделе «Мои 📺 каналы».",
                show_alert=True,
            )
            return
        source_id = int(row["source_id"])
        src = await get_source_row(user_id, source_id)
        if not src or not src["enabled"]:
            await callback.answer("Источник выключен или недоступен.", show_alert=True)
            return
        await callback.answer()
        title = escape(str(row.get("source_feed_title") or "—"))
        await callback.bot.send_message(
            user_id,
            "<b>Выставить в канал</b>\n\n"
            f"Новость <b>#{inbox_id}</b> · источник <b>#{source_id}</b> · {title}\n\n"
            "Выбери канал:",
            parse_mode="HTML",
            reply_markup=publish_one_post_channel_pick_kb(inbox_id, chs),
        )
        return

    if (
        len(parts) == 4
        and parts[1] == "doib"
        and parts[2].isdigit()
        and parts[3].isdigit()
    ):
        inbox_id = int(parts[2])
        ch_row_id = int(parts[3])
        row_in = await news_inbox_get(user_id, inbox_id)
        if not row_in:
            await callback.answer("Запись уже удалена из очереди.", show_alert=True)
            return
        source_id = int(row_in["source_id"])
        settings = load_settings()
        has_ai_key = bool((settings.openai_api_key or "").strip())
        if not has_ai_key and not settings.openai_fallback_plain_text:
            await callback.answer(
                "Нужен OPENAI_API_KEY или включи OPENAI_FALLBACK_PLAIN_TEXT=1 в .env.",
                show_alert=True,
            )
            return
        jid = await get_manual_publish_job(user_id, source_id, ch_row_id)
        if not jid:
            await callback.answer("Не удалось сопоставить канал и источник.", show_alert=True)
            return
        ps = await get_posting_settings(user_id)
        if await get_daily_post_count(user_id) >= int(ps["max_posts_per_day"]):
            await callback.answer("Достигнут лимит постов на сегодня", show_alert=True)
            return
        snap = inbox_publish_target.get((user_id, inbox_id))
        if not snap:
            await compose_inbox_detail(user_id, inbox_id)
            snap = inbox_publish_target.get((user_id, inbox_id))
        if not snap:
            await callback.answer("Не удалось подготовить запись.", show_alert=True)
            return
        pend = post_once_pending.get(user_id)
        p_fid = pend.get("override_photo_file_id") if pend else None
        oid_combo = p_fid if isinstance(p_fid, str) else inbox_channel_photo_override.get(
            (user_id, inbox_id)
        )
        has_photo = bool(
            oid_combo or (snap.built and snap.built.image_urls),
        )
        if not has_photo:
            await callback.answer(
                "В посте должно быть фото. Нажми «Изменить» и пришли фото с подписью.",
                show_alert=True,
            )
            return
        entry_key = snap.item.entry_key
        item_link = (snap.item.link or "").strip()
        posted_already = await is_entry_posted(source_id, entry_key)
        force_repost = posted_already
        if item_link and not force_repost and await is_duplicate_article_for_user(user_id, item_link):
            await mark_entry_posted(source_id, entry_key)
            await news_inbox_delete(user_id, inbox_id)
            inbox_publish_target.pop((user_id, inbox_id), None)
            inbox_channel_photo_override.pop((user_id, inbox_id), None)
            post_once_pending.pop(user_id, None)
            await callback.answer(
                "Эта новость уже публиковалась (совпала ссылка с другой публикацией).",
                show_alert=True,
            )
            return
        prev_mid = pend.get("preview_message_id") if pend else None
        prev_cid = pend.get("preview_chat_id") if pend else None
        await callback.answer("Публикую…")
        if callback.message:
            try:
                await callback.message.delete()
            except TelegramBadRequest:
                pass
        status = await callback.bot.send_message(user_id, "Публикую в канал…")
        oid = oid_combo if isinstance(oid_combo, str) else None
        try:
            outcome = await process_one_feed_job(
                callback.bot,
                settings,
                jid,
                ignore_user_posting_rules=True,
                only_entry_key=entry_key,
                force_repost=force_repost,
                fallback_feed_item=snap.item,
                prebuilt=snap.built,
                user_photo_file_id=oid,
            )
        except Exception:  # noqa: BLE001
            logging.exception("post_once doib publish")
            await status.edit_text("Ошибка при публикации.")
            return
        if outcome.ok:
            await news_inbox_delete(user_id, inbox_id)
            inbox_publish_target.pop((user_id, inbox_id), None)
            inbox_channel_photo_override.pop((user_id, inbox_id), None)
            post_once_pending.pop(user_id, None)
            if isinstance(prev_mid, int) and prev_cid is not None:
                try:
                    await callback.bot.delete_message(
                        chat_id=int(prev_cid),
                        message_id=prev_mid,
                    )
                except TelegramBadRequest:
                    pass
        await status.edit_text(
            "Готово — проверь канал."
            if outcome.ok
            else (outcome.user_message or "Не удалось опубликовать.")
        )
        return

    await callback.answer()


async def _refresh_publish_one_preview_message(
    bot: Bot,
    *,
    user_id: int,
    inbox_id: int,
    chat_id: int,
    message_id: int,
    preview_kind: str,
) -> None:
    rend = await render_stored_inbox_detail(user_id, inbox_id)
    kb = publish_one_post_actions_kb(inbox_id)
    if not rend:
        return
    html, _, _ = rend
    html_safe = _html_for_edit_message(html)
    snap = inbox_publish_target.get((user_id, inbox_id))
    post_plain = (snap.built.text if snap and snap.built else "") or ""
    if preview_kind == "photo":
        cap = _preview_photo_caption(post_plain)
        try:
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=cap[:1024],
                reply_markup=kb,
            )
        except TelegramBadRequest:
            logging.exception("edit_message_caption publish_one preview")
        return
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=html_safe,
            parse_mode="HTML",
            reply_markup=kb,
        )
    except TelegramBadRequest:
        logging.exception("edit_message_text publish_one preview")


async def post_once_edit_inbox_photo(message: Message, state: FSMContext) -> None:
    if not message.photo or not message.from_user:
        return
    await ensure_user(message.from_user.id)
    user_id = message.from_user.id
    data = await state.get_data()
    inbox_id = data.get("inbox_id")
    chat_id = data.get("target_chat_id")
    msg_id = data.get("target_message_id")
    preview_kind = data.get("preview_kind") or "text"
    if not isinstance(inbox_id, int) or chat_id is None or msg_id is None:
        await state.clear()
        return
    snap = inbox_publish_target.get((user_id, inbox_id))
    if not snap:
        await state.clear()
        await message.answer("Сессия устарела. Открой снова «Опубликовать 1 пост».")
        return
    raw = (message.caption or "").strip()
    text = sanitize_post_text(raw) if raw else ""
    if not text:
        if snap.built:
            text = snap.built.text
        else:
            fb = f"{snap.item.title}\n\n{snap.item.body_text}".strip()
            text = sanitize_post_text(fb) if fb else "—"
    file_id = message.photo[-1].file_id
    if snap.built:
        new_built = BuiltPost(
            rewritten=snap.built.rewritten,
            ai_note=snap.built.ai_note,
            text=text,
            body_for_images=snap.built.body_for_images,
            image_urls=[file_id],
        )
    else:
        new_built = BuiltPost(
            rewritten=(snap.item.body_text or ""),
            ai_note="",
            text=text,
            body_for_images=_truncate_plain(snap.item.body_text, 8000),
            image_urls=[file_id],
        )
    inbox_publish_target[(user_id, inbox_id)] = DraftPublishSnapshot(
        item=snap.item,
        kind=snap.kind,
        built=new_built,
    )
    inbox_channel_photo_override[(user_id, inbox_id)] = file_id
    pnd = post_once_pending.setdefault(user_id, {})
    pnd["inbox_id"] = inbox_id
    pnd["override_photo_file_id"] = file_id
    pnd["preview_kind"] = "photo"
    pnd["preview_chat_id"] = chat_id
    pnd["preview_message_id"] = msg_id
    cap = _preview_photo_caption(text)
    try:
        await message.bot.edit_message_media(
            chat_id=int(chat_id),
            message_id=int(msg_id),
            media=InputMediaPhoto(media=file_id, caption=cap[:1024]),
            reply_markup=publish_one_post_actions_kb(inbox_id),
        )
    except TelegramBadRequest:
        try:
            await message.bot.delete_message(chat_id=int(chat_id), message_id=int(msg_id))
        except TelegramBadRequest:
            pass
        sent = await message.bot.send_photo(
            int(chat_id),
            photo=file_id,
            caption=cap[:1024],
            reply_markup=publish_one_post_actions_kb(inbox_id),
        )
        pnd["preview_message_id"] = sent.message_id
        await state.update_data(target_message_id=sent.message_id)
    await state.clear()
    await message.answer("Готово — предпросмотр обновлён.")


async def post_once_edit_inbox_text(message: Message, state: FSMContext) -> None:
    if not message.from_user or not message.text:
        return
    if message.text.strip().startswith("/"):
        return
    user_id = message.from_user.id
    data = await state.get_data()
    inbox_id = data.get("inbox_id")
    chat_id = data.get("target_chat_id")
    msg_id = data.get("target_message_id")
    preview_kind = data.get("preview_kind") or "text"
    if not isinstance(inbox_id, int) or chat_id is None or msg_id is None:
        await state.clear()
        return
    snap = inbox_publish_target.get((user_id, inbox_id))
    if not snap:
        await state.clear()
        await message.answer("Сессия устарела. Открой снова «Опубликовать 1 пост».")
        return
    new_text = sanitize_post_text(message.text)
    if snap.built:
        new_built = BuiltPost(
            rewritten=snap.built.rewritten,
            ai_note=snap.built.ai_note,
            text=new_text,
            body_for_images=snap.built.body_for_images,
            image_urls=list(snap.built.image_urls),
        )
    else:
        new_built = BuiltPost(
            rewritten=(snap.item.body_text or ""),
            ai_note="",
            text=new_text,
            body_for_images=_truncate_plain(snap.item.body_text, 8000),
            image_urls=[],
        )
    inbox_publish_target[(user_id, inbox_id)] = DraftPublishSnapshot(
        item=snap.item,
        kind=snap.kind,
        built=new_built,
    )
    if preview_kind == "photo":
        cap = _preview_photo_caption(new_text)
        try:
            await message.bot.edit_message_caption(
                chat_id=int(chat_id),
                message_id=int(msg_id),
                caption=cap[:1024],
                reply_markup=publish_one_post_actions_kb(inbox_id),
            )
        except TelegramBadRequest:
            logging.exception("post_once text→caption")
    else:
        await _refresh_publish_one_preview_message(
            message.bot,
            user_id=user_id,
            inbox_id=inbox_id,
            chat_id=int(chat_id),
            message_id=int(msg_id),
            preview_kind="text",
        )
    await state.clear()
    await message.answer("Готово — текст обновлён в предпросмотре.")


async def post_once_cancel_cmd(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.")


async def draft_edit_cancel_cmd(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Редактирование черновика отменено.")


async def draft_edit_receive_photo(message: Message, state: FSMContext) -> None:
    if not message.photo or not message.from_user:
        return
    await ensure_user(message.from_user.id)
    user_id = message.from_user.id
    data = await state.get_data()
    sid = data.get("source_id")
    iid = data.get("inbox_id")
    if isinstance(iid, int):
        snap = inbox_publish_target.get((user_id, iid))
        if not snap:
            await state.clear()
            await message.answer("Сессия устарела. Открой новость снова из списка.")
            return
        raw = (message.caption or "").strip()
        text = sanitize_post_text(raw) if raw else ""
        if not text:
            if snap.built:
                text = snap.built.text
            else:
                fb = f"{snap.item.title}\n\n{snap.item.body_text}".strip()
                text = sanitize_post_text(fb) if fb else "—"
        file_id = message.photo[-1].file_id
        inbox_channel_photo_override[(user_id, iid)] = file_id
        if snap.built:
            new_built = BuiltPost(
                rewritten=snap.built.rewritten,
                ai_note=snap.built.ai_note,
                text=text,
                body_for_images=snap.built.body_for_images,
                image_urls=[file_id],
            )
        else:
            new_built = BuiltPost(
                rewritten=(snap.item.body_text or ""),
                ai_note="",
                text=text,
                body_for_images=_truncate_plain(snap.item.body_text, 8000),
                image_urls=[file_id],
            )
        inbox_publish_target[(user_id, iid)] = DraftPublishSnapshot(
            item=snap.item,
            kind=snap.kind,
            built=new_built,
        )
        await state.clear()
        await _show_stored_inbox_view_messages(message, user_id, iid)
        return
    if not isinstance(sid, int):
        await state.clear()
        return
    snap = draft_publish_target.get((user_id, sid))
    if not snap:
        await state.clear()
        await message.answer("Сессия устарела. Открой черновик снова из списка.")
        return
    raw = (message.caption or "").strip()
    text = sanitize_post_text(raw) if raw else ""
    if not text:
        if snap.built:
            text = snap.built.text
        else:
            fb = f"{snap.item.title}\n\n{snap.item.body_text}".strip()
            text = sanitize_post_text(fb) if fb else "—"
    file_id = message.photo[-1].file_id
    draft_channel_photo_override[(user_id, sid)] = file_id
    if snap.built:
        new_built = BuiltPost(
            rewritten=snap.built.rewritten,
            ai_note=snap.built.ai_note,
            text=text,
            body_for_images=snap.built.body_for_images,
            image_urls=[file_id],
        )
    else:
        new_built = BuiltPost(
            rewritten=(snap.item.body_text or ""),
            ai_note="",
            text=text,
            body_for_images=_truncate_plain(snap.item.body_text, 8000),
            image_urls=[file_id],
        )
    draft_publish_target[(user_id, sid)] = DraftPublishSnapshot(
        item=snap.item,
        kind=snap.kind,
        built=new_built,
    )
    await state.clear()
    await _show_stored_draft_view_messages(message, user_id, sid)


async def draft_edit_receive_text(message: Message, state: FSMContext) -> None:
    if not message.from_user or not message.text:
        return
    if message.text.strip().startswith("/"):
        return
    user_id = message.from_user.id
    data = await state.get_data()
    sid = data.get("source_id")
    iid = data.get("inbox_id")
    if isinstance(iid, int):
        snap = inbox_publish_target.get((user_id, iid))
        if not snap:
            await state.clear()
            await message.answer("Сессия устарела. Открой новость снова из списка.")
            return
        new_text = sanitize_post_text(message.text)
        if snap.built:
            new_built = BuiltPost(
                rewritten=snap.built.rewritten,
                ai_note=snap.built.ai_note,
                text=new_text,
                body_for_images=snap.built.body_for_images,
                image_urls=list(snap.built.image_urls),
            )
        else:
            new_built = BuiltPost(
                rewritten=(snap.item.body_text or ""),
                ai_note="",
                text=new_text,
                body_for_images=_truncate_plain(snap.item.body_text, 8000),
                image_urls=[],
            )
        inbox_publish_target[(user_id, iid)] = DraftPublishSnapshot(
            item=snap.item,
            kind=snap.kind,
            built=new_built,
        )
        await state.clear()
        await _show_stored_inbox_view_messages(message, user_id, iid)
        return
    if not isinstance(sid, int):
        await state.clear()
        return
    snap = draft_publish_target.get((user_id, sid))
    if not snap:
        await state.clear()
        await message.answer("Сессия устарела. Открой черновик снова из списка.")
        return
    new_text = sanitize_post_text(message.text)
    if snap.built:
        new_built = BuiltPost(
            rewritten=snap.built.rewritten,
            ai_note=snap.built.ai_note,
            text=new_text,
            body_for_images=snap.built.body_for_images,
            image_urls=list(snap.built.image_urls),
        )
    else:
        new_built = BuiltPost(
            rewritten=(snap.item.body_text or ""),
            ai_note="",
            text=new_text,
            body_for_images=_truncate_plain(snap.item.body_text, 8000),
            image_urls=[],
        )
    draft_publish_target[(user_id, sid)] = DraftPublishSnapshot(
        item=snap.item,
        kind=snap.kind,
        built=new_built,
    )
    await state.clear()
    await _show_stored_draft_view_messages(message, user_id, sid)


async def inbox_router(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data or not callback.message or not callback.from_user:
        return
    await ensure_user(callback.from_user.id)
    user_id = callback.from_user.id
    parts = (callback.data or "").split(":")

    if not parts or parts[0] != "inb":
        await callback.answer()
        return

    if len(parts) == 3 and parts[1] == "v" and parts[2].isdigit():
        iid = int(parts[2])
        if not await news_inbox_get(user_id, iid):
            await callback.answer("Запись не найдена или уже удалена.", show_alert=True)
            await _refresh_news_list_callback(callback, user_id)
            return
        if not await _show_inbox_view(callback, user_id, iid):
            logging.error("inbox: не удалось обновить сообщение (edit_text)")
            await callback.answer("Не удалось обновить сообщение.", show_alert=True)
            return
        await callback.answer()
        return

    if len(parts) == 3 and parts[1] == "e" and parts[2].isdigit():
        iid = int(parts[2])
        if not await news_inbox_get(user_id, iid):
            await callback.answer("Запись не найдена.", show_alert=True)
            return
        snap = inbox_publish_target.get((user_id, iid))
        if not snap:
            await callback.answer("Открой новость снова из списка.", show_alert=True)
            return
        await state.clear()
        await state.set_state(DraftEditStates.wait_edit)
        await state.update_data(inbox_id=iid)
        await callback.answer()
        await callback.message.answer(
            "✏️ <b>Изменение поста</b>\n\n"
            "Пришли <b>текст</b> одним сообщением — он заменит текст поста "
            "(картинки из ленты останутся, если не отправляешь своё фото).\n"
            "Или пришли <b>фото</b> с подписью — в канал пойдёт это фото и текст из подписи "
            "(если подписи нет, останется прежний текст поста).\n\n"
            "<i>Отмена:</i> /cancel",
            parse_mode="HTML",
        )
        return

    if len(parts) == 3 and parts[1] == "pickc" and parts[2].isdigit():
        await _inbox_open_channel_picker(callback, user_id, int(parts[2]))
        return

    if (
        len(parts) == 4
        and parts[1] == "pub"
        and parts[2].isdigit()
        and parts[3].isdigit()
    ):
        inbox_id = int(parts[2])
        ch_row_id = int(parts[3])
        row_in = await news_inbox_get(user_id, inbox_id)
        if not row_in:
            await callback.answer("Запись уже удалена из очереди.", show_alert=True)
            await _refresh_news_list_callback(callback, user_id)
            return
        source_id = int(row_in["source_id"])
        settings = load_settings()
        has_ai_key = bool((settings.openai_api_key or "").strip())
        if not has_ai_key and not settings.openai_fallback_plain_text:
            await callback.answer(
                "Нужен OPENAI_API_KEY или включи OPENAI_FALLBACK_PLAIN_TEXT=1 в .env.",
                show_alert=True,
            )
            return
        jid = await get_manual_publish_job(user_id, source_id, ch_row_id)
        if not jid:
            await callback.answer("Источник выключен или канал не сопоставлен.", show_alert=True)
            return
        ps = await get_posting_settings(user_id)
        if await get_daily_post_count(user_id) >= int(ps["max_posts_per_day"]):
            await callback.answer("Достигнут лимит постов на сегодня", show_alert=True)
            return
        snap = inbox_publish_target.get((user_id, inbox_id))
        if not snap:
            await compose_inbox_detail(user_id, inbox_id)
            snap = inbox_publish_target.get((user_id, inbox_id))
            if not snap:
                await callback.answer("Не удалось подготовить запись.", show_alert=True)
                return
        entry_key = snap.item.entry_key
        item_link = (snap.item.link or "").strip()
        posted_already = await is_entry_posted(source_id, entry_key)
        force_repost = posted_already
        if item_link and not force_repost and await is_duplicate_article_for_user(user_id, item_link):
            await mark_entry_posted(source_id, entry_key)
            await news_inbox_delete(user_id, inbox_id)
            inbox_publish_target.pop((user_id, inbox_id), None)
            inbox_channel_photo_override.pop((user_id, inbox_id), None)
            await callback.answer(
                "Эта новость уже публиковалась (совпала ссылка с другой публикацией).",
                show_alert=True,
            )
            await _refresh_news_list_callback(callback, user_id)
            return
        await callback.answer("Публикую…")
        status = await callback.message.answer("Публикую в канал…")
        override_fid = inbox_channel_photo_override.get((user_id, inbox_id))
        try:
            outcome = await process_one_feed_job(
                callback.bot,
                settings,
                jid,
                ignore_user_posting_rules=True,
                only_entry_key=entry_key,
                force_repost=force_repost,
                fallback_feed_item=snap.item,
                prebuilt=snap.built,
                user_photo_file_id=override_fid,
            )
        except Exception:  # noqa: BLE001
            logging.exception("inbox post")
            await status.edit_text("Ошибка при публикации.")
            return
        if outcome.ok:
            await news_inbox_delete(user_id, inbox_id)
            inbox_publish_target.pop((user_id, inbox_id), None)
            inbox_channel_photo_override.pop((user_id, inbox_id), None)
        await status.edit_text(
            "Готово — проверь канал."
            if outcome.ok
            else (outcome.user_message or "Не удалось опубликовать.")
        )
        await _refresh_news_list_callback(callback, user_id)
        return

    if len(parts) == 3 and parts[1] == "next" and parts[2].isdigit():
        inbox_id = int(parts[2])
        ids_before = await news_inbox_ordered_ids(user_id)
        if inbox_id not in ids_before:
            await callback.answer("Запись уже удалена.", show_alert=True)
            await _refresh_news_list_callback(callback, user_id)
            return
        idx = ids_before.index(inbox_id)
        next_id = ids_before[idx + 1] if idx + 1 < len(ids_before) else None
        await news_inbox_delete(user_id, inbox_id)
        inbox_publish_target.pop((user_id, inbox_id), None)
        inbox_channel_photo_override.pop((user_id, inbox_id), None)
        await callback.answer("Удалено из очереди")
        if next_id is not None:
            if not await _show_inbox_view(callback, user_id, next_id):
                await _refresh_news_list_callback(callback, user_id)
            return
        await _refresh_news_list_callback(callback, user_id)
        return

    await callback.answer()


async def draft_router(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data or not callback.message or not callback.from_user:
        return
    await ensure_user(callback.from_user.id)
    user_id = callback.from_user.id
    parts = (callback.data or "").split(":")

    if len(parts) == 3 and parts[0] == "d" and parts[1] == "v" and parts[2].isdigit():
        sid = int(parts[2])
        row = await get_source_row(user_id, sid)
        if not row or not row["enabled"]:
            await callback.answer("Источник не найден или выключен.", show_alert=True)
            return
        if not await _show_draft_view(callback, user_id, sid):
            logging.error("Черновик: не удалось обновить сообщение (edit_text)")
            await callback.answer("Не удалось обновить сообщение.", show_alert=True)
            return
        await callback.answer()
        return

    if len(parts) == 3 and parts[0] == "d" and parts[1] == "e" and parts[2].isdigit():
        sid = int(parts[2])
        row = await get_source_row(user_id, sid)
        if not row or not row["enabled"]:
            await callback.answer("Источник не найден или выключен.", show_alert=True)
            return
        snap = draft_publish_target.get((user_id, sid))
        if not snap:
            await callback.answer("Открой черновик снова из списка.", show_alert=True)
            return
        await state.set_state(DraftEditStates.wait_edit)
        await state.update_data(source_id=sid)
        await callback.answer()
        await callback.message.answer(
            "✏️ <b>Изменение черновика</b>\n\n"
            "Пришли <b>текст</b> одним сообщением — он заменит текст поста "
            "(картинки из ленты останутся, если не отправляешь своё фото).\n"
            "Или пришли <b>фото</b> с подписью — в канал пойдёт это фото и текст из подписи "
            "(если подписи нет, останется прежний текст поста).\n\n"
            "<i>Отмена:</i> /cancel",
            parse_mode="HTML",
        )
        return

    if len(parts) == 3 and parts[0] == "d" and parts[1] == "pickc" and parts[2].isdigit():
        await _draft_open_channel_picker(callback, user_id, int(parts[2]))
        return

    if len(parts) == 3 and parts[0] == "d" and parts[1] == "p" and parts[2].isdigit():
        await _draft_open_channel_picker(callback, user_id, int(parts[2]))
        return

    if (
        len(parts) == 4
        and parts[0] == "d"
        and parts[1] == "pub"
        and parts[2].isdigit()
        and parts[3].isdigit()
    ):
        sid = int(parts[2])
        ch_row_id = int(parts[3])
        settings = load_settings()
        has_ai_key = bool((settings.openai_api_key or "").strip())
        if not has_ai_key and not settings.openai_fallback_plain_text:
            await callback.answer(
                "Нужен OPENAI_API_KEY или включи OPENAI_FALLBACK_PLAIN_TEXT=1 в .env.",
                show_alert=True,
            )
            return
        jid = await get_manual_publish_job(user_id, sid, ch_row_id)
        if not jid:
            await callback.answer("Не удалось сопоставить канал и источник.", show_alert=True)
            return
        ps = await get_posting_settings(user_id)
        if await get_daily_post_count(user_id) >= int(ps["max_posts_per_day"]):
            await callback.answer("Достигнут лимит постов на сегодня", show_alert=True)
            return
        row = await get_source_row(user_id, sid)
        if not row:
            await callback.answer("Источник не найден", show_alert=True)
            return
        snap = draft_publish_target.get((user_id, sid))
        if not snap:
            sug = await get_draft_suggestion(user_id, sid, str(row["url"]))
            if not sug:
                await callback.answer("Лента пуста или недоступна", show_alert=True)
                return
            snap = DraftPublishSnapshot(item=sug.item, kind=sug.kind)
            draft_publish_target[(user_id, sid)] = snap
        entry_key = snap.item.entry_key
        kind = snap.kind
        item_link = (snap.item.link or "").strip()
        posted_already = await is_entry_posted( sid, entry_key)
        force_repost = kind == "repeat" or posted_already
        if item_link and not force_repost and await is_duplicate_article_for_user(user_id, item_link):
            await mark_entry_posted(sid, entry_key)
            await news_inbox_delete_by_entry_key(user_id, sid, entry_key)
            draft_publish_target.pop((user_id, sid), None)
            draft_channel_photo_override.pop((user_id, sid), None)
            await callback.answer(
                "Эта новость уже публиковалась (совпала ссылка с другой публикацией).",
                show_alert=True,
            )
            await _refresh_news_list_callback(callback, user_id)
            return
        await callback.answer("Публикую…")
        status = await callback.message.answer("Публикую в канал…")
        override_fid = draft_channel_photo_override.get((user_id, sid))
        try:
            outcome = await process_one_feed_job(
                callback.bot,
                settings,
                jid,
                ignore_user_posting_rules=True,
                only_entry_key=entry_key,
                force_repost=force_repost,
                fallback_feed_item=snap.item,
                prebuilt=snap.built,
                user_photo_file_id=override_fid,
            )
        except Exception:  # noqa: BLE001
            logging.exception("draft post")
            await status.edit_text("Ошибка при публикации.")
            return
        if outcome.ok:
            await news_inbox_delete_by_entry_key(user_id, sid, entry_key)
            draft_publish_target.pop((user_id, sid), None)
            draft_channel_photo_override.pop((user_id, sid), None)
        await status.edit_text(
            "Готово — проверь канал."
            if outcome.ok
            else (outcome.user_message or "Не удалось опубликовать.")
        )
        await _refresh_news_list_callback(callback, user_id)
        return

    if len(parts) == 3 and parts[0] == "d" and parts[1] == "k" and parts[2].isdigit():
        sid = int(parts[2])
        row = await get_source_row(user_id, sid)
        if not row:
            await callback.answer()
            return
        sug = await get_draft_suggestion(user_id, sid, str(row["url"]))
        if not sug:
            await callback.answer("Нечего пропускать", show_alert=True)
            return
        if sug.kind == "repeat":
            await callback.answer(
                "Все свежие записи уже отмечены — «Пропустить» не нужен. "
                "Можно отправить снова или дождаться новых в ленте.",
                show_alert=True,
            )
            return
        await mark_entry_posted(sid, sug.item.entry_key)
        await news_inbox_delete_by_entry_key(user_id, sid, sug.item.entry_key)
        draft_publish_target.pop((user_id, sid), None)
        draft_channel_photo_override.pop((user_id, sid), None)
        await callback.answer("Пропущено")
        rows = await list_rss_sources(user_id)
        enabled = _enabled_sources(rows)
        order = _draft_source_ids_after_skip(enabled, sid)
        for cand in order:
            row_c = await get_source_row(user_id, cand)
            if not row_c or not row_c["enabled"]:
                continue
            if not await get_draft_suggestion(user_id, cand, str(row_c["url"])):
                continue
            if await _show_draft_view(callback, user_id, cand):
                return
        await _refresh_news_list_callback(callback, user_id)
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

    if action == "mode" and len(parts) == 3 and parts[2] in ("manual", "auto"):
        cfg = load_settings()
        if parts[2] == "auto" and not cfg.allow_auto_posting:
            await callback.answer(
                "Авто пост в канал отключён. Добавь в .env ALLOW_AUTO_POSTING=1 и перезапусти бота.",
                show_alert=True,
            )
            return
        await update_posting_settings(user_id, posting_mode=parts[2])
        await callback.answer("Режим сохранён")
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


def _telegram_http_session(settings: Settings) -> AiohttpSession:
    """Сессия для Bot API: опциональный прокси и таймаут (см. TELEGRAM_* в .env)."""
    timeout = float(settings.telegram_http_timeout)
    if settings.telegram_proxy:
        return AiohttpSession(proxy=settings.telegram_proxy, timeout=timeout)
    return AiohttpSession(timeout=timeout)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    settings = load_settings()
    if settings.telegram_proxy:
        logging.getLogger(__name__).info(
            "TELEGRAM_PROXY задан — запросы к Bot API идут через прокси."
        )
    await init_db()

    bot = Bot(token=settings.bot_token, session=_telegram_http_session(settings))
    dp = Dispatcher(storage=MemoryStorage())

    asyncio.create_task(run_post_worker_loop(bot))
    asyncio.create_task(run_rss_monitor_loop())

    dp.message.register(cmd_start, CommandStart())
    dp.callback_query.register(inbox_router, F.data.startswith("inb:"))
    dp.callback_query.register(draft_router, F.data.startswith("d:"))
    dp.callback_query.register(deprecated_link_callback, F.data.startswith("l:"))
    dp.callback_query.register(source_delete_router, F.data.startswith("sd:"))
    dp.callback_query.register(post_once_router, F.data.startswith("po:"))
    dp.callback_query.register(menu_router, F.data.startswith("menu:"))
    dp.callback_query.register(channels_router, F.data.startswith("ch:"))
    dp.callback_query.register(sources_router, F.data.startswith("src:"))
    dp.callback_query.register(posting_settings_router, F.data.startswith("ps:"))
    dp.message.register(
        draft_edit_receive_photo,
        StateFilter(DraftEditStates.wait_edit),
        F.photo,
    )
    dp.message.register(
        draft_edit_cancel_cmd,
        StateFilter(DraftEditStates.wait_edit),
        Command("cancel"),
    )
    dp.message.register(
        draft_edit_receive_text,
        StateFilter(DraftEditStates.wait_edit),
        F.text & ~F.text.startswith("/"),
    )
    dp.message.register(
        post_once_edit_inbox_photo,
        StateFilter(PostOnceStates.wait_edit_inbox),
        F.photo,
    )
    dp.message.register(
        post_once_edit_inbox_text,
        StateFilter(PostOnceStates.wait_edit_inbox),
        F.text & ~F.text.startswith("/"),
    )
    dp.message.register(
        post_once_cancel_cmd,
        StateFilter(PostOnceStates.wait_edit_inbox),
        Command("cancel"),
    )
    dp.message.register(on_text_message, F.text & ~F.text.startswith("/"))

    # Иначе Telegram отдаёт Conflict, если у бота остался webhook или второй процесс polling.
    log = logging.getLogger(__name__)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        me = await bot.get_me()
    except TelegramNetworkError as exc:
        await bot.session.close()
        log.error(
            "Нет связи с Telegram API (api.telegram.org). Типично: блокировка, фаервол или нужен VPN.\n"
            "Что сделать: включи VPN с доступом к Telegram ИЛИ добавь в .env строку\n"
            "  TELEGRAM_PROXY=socks5://127.0.0.1:ПОРТ\n"
            "(порт возьми из настроек прокси VPN-клиента; для http-прокси — http://...).\n"
            "Нужен пакет: pip install aiohttp-socks\n"
            "Детали ошибки: %s",
            exc,
        )
        raise SystemExit(1) from exc

    log.info(
        "Telegram: polling для @%s (id=%s). Дальше логов по умолчанию мало — бот ждёт сообщения.",
        me.username or "—",
        me.id,
    )
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
