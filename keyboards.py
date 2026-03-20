from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Мои 📺 каналы", callback_data="menu:channels")],
            [InlineKeyboardButton(text="Мои 📰 источники", callback_data="menu:sources")],
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


def sources_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Добавить источник", callback_data="src:add")],
            [InlineKeyboardButton(text="Привязать к каналу", callback_data="src:link")],
            [InlineKeyboardButton(text="Удалить источник", callback_data="src:del")],
            [InlineKeyboardButton(text="Опубликовать 1 пост", callback_data="src:post_once")],
            [InlineKeyboardButton(text="Обновить список", callback_data="menu:sources")],
            [InlineKeyboardButton(text="« Главное меню", callback_data="menu:home")],
        ]
    )


def posting_settings_kb(
    *,
    posting_enabled: bool,
    send_images: bool,
    quiet_enabled: bool,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"Автопост: {'ON' if posting_enabled else 'OFF'}",
                    callback_data="ps:toggle_posting",
                ),
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
