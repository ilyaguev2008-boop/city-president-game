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
            [KeyboardButton(text="⚽ Футбольные ленты (набор)")],
            [KeyboardButton(text="🗑 Удалить источник новостей")],
            [KeyboardButton(text="📤 Опубликовать 1 пост")],
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
            [
                InlineKeyboardButton(
                    text="⚽ Футбольные ленты",
                    callback_data="src:football",
                )
            ],
            [InlineKeyboardButton(text="Удалить источник новостей", callback_data="src:del")],
            [InlineKeyboardButton(text="Опубликовать 1 пост", callback_data="src:post_once")],
            [InlineKeyboardButton(text="« Главное меню", callback_data="menu:home")],
        ]
    )


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


def publish_one_post_screen_kb() -> InlineKeyboardMarkup:
    """Экран «Опубликовать 1 пост»: список в тексте сообщения, свежая новость приходит отдельным сообщением."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить список", callback_data="src:post_once")],
            [InlineKeyboardButton(text="📰 Источники новостей", callback_data="menu:sources")],
            [InlineKeyboardButton(text="« Главное меню", callback_data="menu:home")],
        ]
    )


def publish_one_post_actions_kb(inbox_id: int) -> InlineKeyboardMarkup:
    """Действия над предпросмотром самой свежей новости."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Изменить",
                    callback_data=f"po:editib:{inbox_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⏭ Пропустить и удалить",
                    callback_data=f"po:skipib:{inbox_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📤 Выставить",
                    callback_data=f"po:pickib:{inbox_id}",
                ),
            ],
        ]
    )


def publish_one_post_channel_pick_kb(
    inbox_id: int, channels: list[dict[str, object]]
) -> InlineKeyboardMarkup:
    lines: list[list[InlineKeyboardButton]] = []
    for ch in channels:
        cid = int(ch["id"])
        title = _btn_short(str(ch.get("title") or "Без названия"), 32)
        lines.append(
            [
                InlineKeyboardButton(
                    text=f"📺 #{cid} · {title}",
                    callback_data=f"po:doib:{inbox_id}:{cid}",
                )
            ]
        )
    lines.append(
        [InlineKeyboardButton(text="« Закрыть выбор", callback_data="po:chclose")]
    )
    return InlineKeyboardMarkup(inline_keyboard=lines)


def publish_one_post_empty_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить список", callback_data="src:post_once")],
            [InlineKeyboardButton(text="📰 Источники новостей", callback_data="menu:sources")],
            [InlineKeyboardButton(text="« Главное меню", callback_data="menu:home")],
        ]
    )


def post_once_confirm_kb(source_id: int) -> InlineKeyboardMarkup:
    """После предпросмотра: выбор канала или своя фото+текст."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📺 Отправить в канал…",
                    callback_data=f"po:pick:{source_id}",
                ),
                InlineKeyboardButton(
                    text="✏️ Изменить",
                    callback_data=f"po:edit:{source_id}",
                ),
            ],
            [InlineKeyboardButton(text="« К списку новостей", callback_data="src:post_once")],
            [InlineKeyboardButton(text="« Источники новостей", callback_data="menu:sources")],
        ]
    )


def post_once_channel_pick_kb(source_id: int, channels: list[dict[str, object]]) -> InlineKeyboardMarkup:
    lines: list[list[InlineKeyboardButton]] = []
    for ch in channels:
        cid = int(ch["id"])
        title = _btn_short(str(ch.get("title") or "Без названия"), 32)
        lines.append(
            [
                InlineKeyboardButton(
                    text=f"📺 #{cid} · {title}",
                    callback_data=f"po:do:{source_id}:{cid}",
                )
            ]
        )
    lines.append([InlineKeyboardButton(text="« К предпросмотру", callback_data=f"po:{source_id}")])
    lines.append([InlineKeyboardButton(text="« Источники новостей", callback_data="menu:sources")])
    return InlineKeyboardMarkup(inline_keyboard=lines)


def drafts_list_kb(enabled_sources: list[dict[str, object]]) -> InlineKeyboardMarkup:
    """Устар.: список по источникам; оставлено для старых сообщений."""
    lines: list[list[InlineKeyboardButton]] = []
    for r in enabled_sources:
        sid = int(r["id"])
        title = _btn_short(str(r.get("feed_title") or "—"), 38)
        lines.append(
            [InlineKeyboardButton(text=f"📋 #{sid} · {title}", callback_data=f"d:v:{sid}")]
        )
    lines.append([InlineKeyboardButton(text="Обновить список", callback_data="menu:drafts")])
    lines.append([InlineKeyboardButton(text="📰 Источники новостей", callback_data="menu:sources")])
    lines.append([InlineKeyboardButton(text="« Главное меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=lines)


def news_inbox_empty_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить список", callback_data="menu:drafts")],
            [InlineKeyboardButton(text="« Главное меню", callback_data="menu:home")],
        ]
    )


def news_inbox_list_kb(rows: list[dict[str, object]]) -> InlineKeyboardMarkup:
    """Очередь новых новостей: одна кнопка на запись (id из news_inbox)."""
    lines: list[list[InlineKeyboardButton]] = []
    for r in rows:
        iid = int(r["id"])
        title = _btn_short(str(r.get("title") or "—"), 30)
        sid = int(r["source_id"])
        src = _btn_short(str(r.get("source_feed_title") or "—"), 12)
        pub = r.get("published_at") or r.get("discovered_at") or ""
        time_bit = ""
        if isinstance(pub, str) and pub.strip():
            time_bit = pub.strip()[:16].replace("T", " ") + " · "
        label = _btn_short(f"{time_bit}#{iid} · {title} · #{sid}", 58)
        lines.append([InlineKeyboardButton(text=label, callback_data=f"inb:v:{iid}")])
    lines.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data="menu:drafts")])
    lines.append([InlineKeyboardButton(text="📰 Источники новостей", callback_data="menu:sources")])
    lines.append([InlineKeyboardButton(text="« Главное меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=lines)


def inbox_detail_kb(inbox_id: int) -> InlineKeyboardMarkup:
    """Три действия по очереди + выбор канала (как в черновике)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📺 Куда отправить",
                    callback_data=f"inb:pickc:{inbox_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Изменить",
                    callback_data=f"inb:e:{inbox_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⏭ Дальше и удалить",
                    callback_data=f"inb:next:{inbox_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Вернуться в меню",
                    callback_data="menu:home",
                ),
            ],
        ]
    )


def inbox_channel_pick_kb(inbox_id: int, channels: list[dict[str, object]]) -> InlineKeyboardMarkup:
    lines: list[list[InlineKeyboardButton]] = []
    for ch in channels:
        cid = int(ch["id"])
        title = _btn_short(str(ch.get("title") or "Без названия"), 32)
        lines.append(
            [
                InlineKeyboardButton(
                    text=f"📺 #{cid} · {title}",
                    callback_data=f"inb:pub:{inbox_id}:{cid}",
                )
            ]
        )
    lines.append([InlineKeyboardButton(text="« К новости", callback_data=f"inb:v:{inbox_id}")])
    lines.append([InlineKeyboardButton(text="« К списку новостей", callback_data="menu:drafts")])
    lines.append([InlineKeyboardButton(text="📰 Источники", callback_data="menu:sources")])
    return InlineKeyboardMarkup(inline_keyboard=lines)


def draft_channel_pick_kb(source_id: int, channels: list[dict[str, object]]) -> InlineKeyboardMarkup:
    lines: list[list[InlineKeyboardButton]] = []
    for ch in channels:
        cid = int(ch["id"])
        title = _btn_short(str(ch.get("title") or "Без названия"), 32)
        lines.append(
            [
                InlineKeyboardButton(
                    text=f"📺 #{cid} · {title}",
                    callback_data=f"d:pub:{source_id}:{cid}",
                )
            ]
        )
    lines.append([InlineKeyboardButton(text="« К черновику", callback_data=f"d:v:{source_id}")])
    lines.append([InlineKeyboardButton(text="« К списку новостей", callback_data="menu:drafts")])
    lines.append([InlineKeyboardButton(text="📰 Источники", callback_data="menu:sources")])
    return InlineKeyboardMarkup(inline_keyboard=lines)


def draft_detail_kb(
    source_id: int,
    *,
    can_skip: bool = True,
) -> InlineKeyboardMarkup:
    row1: list[InlineKeyboardButton] = [
        InlineKeyboardButton(
            text="📺 Куда отправить",
            callback_data=f"d:pickc:{source_id}",
        ),
    ]
    if can_skip:
        row1.append(
            InlineKeyboardButton(text="⏭ Пропустить запись", callback_data=f"d:k:{source_id}")
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            row1,
            [
                InlineKeyboardButton(
                    text="✏️ Изменить пост",
                    callback_data=f"d:e:{source_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="« К списку новостей",
                    callback_data="menu:drafts",
                )
            ],
            [InlineKeyboardButton(text="📰 Источники новостей", callback_data="menu:sources")],
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
