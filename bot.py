from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message

from ai_service import complete_chat, split_for_telegram
from config import load_settings
from keyboards import back_to_main_kb, main_menu_kb


def main_menu_text(name: str, *, key_hint: str) -> str:
    return (
        f"Привет, {name}!\n\n"
        "Это бот **автопостинга в Telegram-каналы**: материалы из **твоих** источников "
        "(лучше всего RSS), пересказ на русском, пост без лишних ссылок и с одной картинкой.\n\n"
        "Выбери раздел ниже или напиши вопрос в чат — отвечу по настройке и работе бота."
        f"{key_hint}"
    )


async def cmd_start(message: Message) -> None:
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
    await message.answer(
        "**Команды**\n"
        "/start — главное меню\n"
        "/help — эта справка\n\n"
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
        await callback.message.edit_text(
            "**Мои каналы**\n\n"
            "Здесь будет список каналов, привязанных к твоему аккаунту: имя, ID, "
            "есть ли у бота право публиковать посты, последняя успешная публикация.\n\n"
            "_Сейчас раздел в разработке: данные и действия появятся после подключения БД._",
            parse_mode="Markdown",
            reply_markup=back_to_main_kb(),
        )
        await callback.answer()
        return

    if action == "sources":
        await callback.message.edit_text(
            "**Мои источники информации**\n\n"
            "Здесь ты будешь добавлять **свои** ленты (предпочтительно **RSS/Atom**): "
            "включение и выключение, привязка «источник → канал».\n\n"
            "_Раздел в разработке._",
            parse_mode="Markdown",
            reply_markup=back_to_main_kb(),
        )
        await callback.answer()
        return

    if action == "status":
        await callback.message.edit_text(
            "**Статус**\n\n"
            "Здесь будет сводка: сколько каналов и активных источников, последний пост, "
            "предупреждения (нет ключа ИИ, бот не админ в канале, источник не отвечает).\n\n"
            "_Раздел в разработке._",
            parse_mode="Markdown",
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
            "3. Узнай **ID канала** (например, через ботов вроде @getidsbot или пересланное "
            "сообщение с канала — формат часто `-100…`).\n"
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
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_help, Command("help"))
    dp.callback_query.register(menu_router, F.data.startswith("menu:"))
    dp.message.register(ai_reply, F.text & ~F.text.startswith("/"))

    # Иначе Telegram отдаёт Conflict, если у бота остался webhook или второй процесс polling.
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
