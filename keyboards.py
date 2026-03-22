from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def _btn_short(text: str, max_len: int = 42) -> str:
    t = (text or "").replace("\n", " ").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def main_menu_reply_kb() -> ReplyKeyboardMarkup:
    """Панель внизу чата — основное меню."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="Мои 📺 каналы"),
                KeyboardButton(text="📰 Источники новостей"),
            ],
            [
                KeyboardButton(text="Статус"),
                KeyboardButton(text="Настройки постинга"),
            ],
            [KeyboardButton(text="Черновики и очередь")],
            [KeyboardButton(text="Помощь")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Ссылка на сайт или вопрос боту…",
    )


def channels_reply_kb() -> ReplyKeyboardMarkup:
    """Панель раздела «Мои каналы»."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="➕ Добавить канал"),
                KeyboardButton(text="🗑 Удалить канал"),
            ],
            [KeyboardButton(text="🔄 Обновить список каналов")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True,
    )


def sources_reply_kb() -> ReplyKeyboardMarkup:
    """Панель раздела «Источники новостей»."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить источник новостей")],
            [KeyboardButton(text="🔗 Привязать к каналу")],
            [KeyboardButton(text="🗑 Удалить источник новостей")],
            [KeyboardButton(text="📤 Опубликовать 1 пост")],
            [KeyboardButton(text="🔄 Обновить список источников")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True,
    )


def main_menu_kb() -> InlineKeyboardMarkup:
    """Устар.: инлайн-меню; оставлено для совместимости со старыми сообщениями."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Мои 📺 каналы", callback_data="menu:channels")],
            [InlineKeyboardButton(text="📰 Источники новостей", callback_data="menu:sources")],
            [InlineKeyboardButton(text="Статус", callback_data="menu:status")],
            [InlineKeyboardButton(text="Настройки постинга", callback_data="menu:settings")],
            [InlineKeyboardButton(text="Черновики и очередь", callback_data="menu:drafts")],
            [InlineKeyboardButton(text="Помощь", callback_data="menu:help")],
        ]
    )


def back_to_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Главное меню", callback_data="menu:home")],
        ]
    )


def channels_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Добавить канал", callback_data="ch:add")],
            [InlineKeyboardButton(text="Удалить канал", callback_data="ch:del")],
            [InlineKeyboardButton(text="Обновить список", callback_data="menu:channels")],
            [InlineKeyboardButton(text="« Главное меню", callback_data="menu:home")],
        ]
    )


def channel_delete_pick_kb(rows: list[dict[str, object]]) -> InlineKeyboardMarkup:
    """rows: list_channels — id, title, chat_id."""
    lines: list[list[InlineKeyboardButton]] = []
    for r in rows:
        sid = int(r["id"])
        title = _btn_short(str(r.get("title") or "Без названия"), 36)
        lines.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 #{sid} · {title}",
                    callback_data=f"ch:x:{sid}",
                )
            ]
        )
    lines.append([InlineKeyboardButton(text="« Назад", callback_data="menu:channels")])
    return InlineKeyboardMarkup(inline_keyboard=lines)


def sources_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Добавить источник новостей", callback_data="src:add")],
            [InlineKeyboardButton(text="Привязать к каналу", callback_data="src:link")],
            [InlineKeyboardButton(text="Удалить источник новостей", callback_data="src:del")],
            [InlineKeyboardButton(text="Опубликовать 1 пост", callback_data="src:post_once")],
            [InlineKeyboardButton(text="Обновить список", callback_data="menu:sources")],
            [InlineKeyboardButton(text="« Главное меню", callback_data="menu:home")],
        ]
    )


def link_pick_source_kb(unlinked: list[dict[str, object]]) -> InlineKeyboardMarkup:
    lines: list[list[InlineKeyboardButton]] = []
    for r in unlinked:
        sid = int(r["id"])
        title = _btn_short(str(r.get("feed_title") or "—"), 36)
        lines.append(
            [InlineKeyboardButton(text=f"#{sid} · {title}", callback_data=f"l:s:{sid}")]
        )
    lines.append([InlineKeyboardButton(text="« Назад", callback_data="menu:sources")])
    return InlineKeyboardMarkup(inline_keyboard=lines)


def link_pick_channel_kb(source_id: int, channels: list[dict[str, object]]) -> InlineKeyboardMarkup:
    lines: list[list[InlineKeyboardButton]] = []
    for ch in channels:
        cid = int(ch["id"])
        title = _btn_short(str(ch.get("title") or "Без названия"), 36)
        lines.append(
            [
                InlineKeyboardButton(
                    text=f"Канал #{cid} · {title}",
                    callback_data=f"l:c:{source_id}:{cid}",
                )
            ]
        )
    lines.append([InlineKeyboardButton(text="« Назад", callback_data="src:link")])
    return InlineKeyboardMarkup(inline_keyboard=lines)


def source_delete_pick_kb(rows: list[dict[str, object]]) -> InlineKeyboardMarkup:
    lines: list[list[InlineKeyboardButton]] = []
    for r in rows:
        sid = int(r["id"])
        title = _btn_short(str(r.get("feed_title") or "—"), 36)
        lines.append(
            [InlineKeyboardButton(text=f"🗑 #{sid} · {title}", callback_data=f"sd:{sid}")]
        )
    lines.append([InlineKeyboardButton(text="« Назад", callback_data="menu:sources")])
    return InlineKeyboardMarkup(inline_keyboard=lines)


def post_once_pick_kb(linked: list[dict[str, object]]) -> InlineKeyboardMarkup:
    lines: list[list[InlineKeyboardButton]] = []
    for r in linked:
        sid = int(r["id"])
        title = _btn_short(str(r.get("feed_title") or "—"), 36)
        lines.append(
            [InlineKeyboardButton(text=f"#{sid} · {title}", callback_data=f"po:{sid}")]
        )
    lines.append([InlineKeyboardButton(text="« Назад", callback_data="menu:sources")])
    return InlineKeyboardMarkup(inline_keyboard=lines)


def drafts_list_kb(linked: list[dict[str, object]]) -> InlineKeyboardMarkup:
    lines: list[list[InlineKeyboardButton]] = []
    for r in linked:
        sid = int(r["id"])
        title = _btn_short(str(r.get("feed_title") or "—"), 38)
        lines.append(
            [InlineKeyboardButton(text=f"📋 #{sid} · {title}", callback_data=f"d:v:{sid}")]
        )
    lines.append([InlineKeyboardButton(text="Обновить", callback_data="menu:drafts")])
    lines.append([InlineKeyboardButton(text="« Главное меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=lines)


def draft_detail_kb(
    source_id: int,
    *,
    can_skip: bool = True,
) -> InlineKeyboardMarkup:
    row1: list[InlineKeyboardButton] = [
        InlineKeyboardButton(text="Опубликовать", callback_data=f"d:p:{source_id}"),
    ]
    if can_skip:
        row1.append(InlineKeyboardButton(text="Пропустить", callback_data=f"d:k:{source_id}"))
    return InlineKeyboardMarkup(
        inline_keyboard=[
            row1,
            [InlineKeyboardButton(text="« К списку черновиков", callback_data="menu:drafts")],
        ]
    )


def posting_settings_kb(
    *,
    posting_mode: str,
    send_images: bool,
    quiet_enabled: bool,
    allow_auto_mode: bool = False,
) -> InlineKeyboardMarkup:
    auto_on = posting_mode == "auto"
    rows: list[list[InlineKeyboardButton]] = []
    if allow_auto_mode:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Ручной{' ✓' if not auto_on else ''}",
                    callback_data="ps:mode:manual",
                ),
                InlineKeyboardButton(
                    text=f"Авто{' ✓' if auto_on else ''}",
                    callback_data="ps:mode:auto",
                ),
            ]
        )
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text=f"Картинки: {'ON' if send_images else 'OFF'}",
                    callback_data="ps:toggle_images",
                ),
            ],
            [
                InlineKeyboardButton(text="Лимит 10/день", callback_data="ps:max:10"),
                InlineKeyboardButton(text="Лимит 20/день", callback_data="ps:max:20"),
                InlineKeyboardButton(text="Лимит 30/день", callback_data="ps:max:30"),
            ],
            [
                InlineKeyboardButton(
                    text=f"Тихие часы: {'ON' if quiet_enabled else 'OFF'}",
                    callback_data="ps:toggle_quiet",
                ),
                InlineKeyboardButton(text="22:00–08:00", callback_data="ps:quiet:22:8"),
                InlineKeyboardButton(text="23:00–07:00", callback_data="ps:quiet:23:7"),
            ],
            [InlineKeyboardButton(text="Обновить", callback_data="ps:refresh")],
            [InlineKeyboardButton(text="« Главное меню", callback_data="menu:home")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
