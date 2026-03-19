from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message

from ai_service import complete_chat, split_for_telegram
from config import load_settings
from keyboards import main_menu_kb


async def cmd_start(message: Message) -> None:
    settings = load_settings()
    name = (message.from_user.full_name if message.from_user else "друг").strip()
    key_hint = ""
    if not settings.openai_api_key:
        key_hint = (
            "\n\n⚠️ Добавь в `.env` ключ `OPENAI_API_KEY=...` "
            "(или совместимый API), затем перезапусти бота."
        )
    text = (
        f"Привет, {name}!\n\n"
        "Я AI-помощник для малого бизнеса: маркетинг, офферы, тексты для клиентов, "
        "идеи продвижения и ценообразование в общих чертах — просто напиши вопрос в чат."
        f"{key_hint}"
    )
    await message.answer(text, reply_markup=main_menu_kb())


async def cmd_help(message: Message) -> None:
    await message.answer(
        "Команды:\n"
        "/start — меню\n"
        "/help — эта справка\n\n"
        "**Как пользоваться:** напиши любой вопрос по бизнесу одним сообщением.\n\n"
        "**Настройка ИИ:** в `.env` задай `OPENAI_API_KEY`, при необходимости "
        "`OPENAI_BASE_URL` (для совместимых API) и `OPENAI_MODEL`.",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )


async def ai_reply(message: Message, bot: Bot) -> None:
    if not message.text or not message.text.strip():
        return
    settings = load_settings()
    if not settings.openai_api_key:
        await message.answer(
            "Ключ ИИ не настроен. Добавь в `.env` строку:\n\n"
            "`OPENAI_API_KEY=sk-...`\n\n"
            "Перезапусти бота и напиши вопрос снова."
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

    for chunk in split_for_telegram(answer):
        if chunk:
            await message.answer(chunk)


async def menu_router(callback: CallbackQuery, state=None) -> None:
    if not callback.data:
        return
    action = callback.data.split(":", 1)[1]

    if action == "home":
        await callback.message.edit_text(
            "Главное меню. Напиши вопрос по бизнесу в чат или нажми «Примеры».",
            reply_markup=main_menu_kb(),
        )
        await callback.answer()
        return

    if action == "about":
        await callback.message.edit_text(
            "Я помогаю самозанятым и малому бизнесу:\n"
            "• тексты постов и ответы клиентам\n"
            "• офферы и акции\n"
            "• идеи продвижения\n"
            "• цена и позиционирование (общие советы)\n"
            "• порядок действий без «магии»\n\n"
            "Пиши вопрос обычным сообщением — отвечу по существу.",
            reply_markup=main_menu_kb(),
        )
        await callback.answer()
        return

    if action == "examples":
        await callback.message.edit_text(
            "Примеры вопросов (скопируй и отправь):\n\n"
            "• У меня салон красоты в Алматы, 2 мастера. Как привлечь клиентов в Instagram за месяц?\n"
            "• Напиши короткий текст поста про скидку 20% на первую запись, тон дружелюбный.\n"
            "• Клиент просит скидку 30%, как ответить вежливо и удержать маржу?\n"
            "• Я делаю сайты на Tilda, как сформулировать оффер для локального бизнеса?\n\n"
            "Добавь своё: город, ниша, средний чек — ответ будет точнее.",
            reply_markup=main_menu_kb(),
        )
        await callback.answer()
        return

    await callback.answer("Не понял действие.")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    settings = load_settings()
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_help, Command("help"))
    dp.callback_query.register(menu_router, F.data.startswith("menu:"))
    dp.message.register(ai_reply, F.text & ~F.text.startswith("/"))

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
