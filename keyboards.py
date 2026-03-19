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
