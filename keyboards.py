from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Примеры вопросов 💡", callback_data="menu:examples")],
            [InlineKeyboardButton(text="Что умеет бот ℹ️", callback_data="menu:about")],
        ]
    )
