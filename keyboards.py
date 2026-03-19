from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


def main_menu_kb(webapp_url: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="Примеры вопросов 💡", callback_data="menu:examples")],
        [InlineKeyboardButton(text="Что умеет бот ℹ️", callback_data="menu:about")],
    ]
    if webapp_url and "example.com" not in webapp_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Доп. Mini App 🔗",
                    web_app=WebAppInfo(url=webapp_url),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)

