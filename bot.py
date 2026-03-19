from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message

from ai_service import complete_chat, split_for_telegram
from config import load_settings
from keyboards import main_menu_kb

STREAMS_FILE = Path(__file__).resolve().parent / "webapp" / "streams.json"


def _default_streams() -> list[dict[str, str]]:
    return [
        {"title": "Матч 1", "url": ""},
        {"title": "Матч 2", "url": ""},
        {"title": "Матч 3", "url": ""},
        {"title": "Матч 4", "url": ""},
    ]


def _load_streams() -> list[dict[str, str]]:
    if not STREAMS_FILE.exists():
        streams = _default_streams()
        _save_streams(streams)
        return streams
    try:
        raw = json.loads(STREAMS_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return _default_streams()
        streams: list[dict[str, str]] = []
        for index in range(4):
            item = raw[index] if index < len(raw) and isinstance(raw[index], dict) else {}
            title = str(item.get("title") or f"Матч {index + 1}")
            url = str(item.get("url") or "")
            streams.append({"title": title, "url": url})
        return streams
    except (OSError, json.JSONDecodeError):
        return _default_streams()


def _save_streams(streams: list[dict[str, str]]) -> None:
    STREAMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STREAMS_FILE.write_text(
        json.dumps(streams, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _is_admin(message: Message) -> bool:
    settings = load_settings()
    user_id = message.from_user.id if message.from_user else None
    return bool(user_id and user_id in settings.admin_ids)


async def cmd_setstream(message: Message) -> None:
    if not _is_admin(message):
        await message.answer("Эта команда только для админа.")
        return

    text = (message.text or "").strip()
    parts = text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer(
            "Используй формат:\n"
            "/setstream <номер 1-4> <url>\n\n"
            "Пример:\n"
            "/setstream 2 https://example.com/embed/match2"
        )
        return

    slot_raw, url = parts[1].strip(), parts[2].strip()
    if not slot_raw.isdigit():
        await message.answer("Номер окна должен быть числом от 1 до 4.")
        return

    slot = int(slot_raw)
    if slot < 1 or slot > 4:
        await message.answer("Номер окна должен быть от 1 до 4.")
        return

    if not (url.startswith("http://") or url.startswith("https://")):
        await message.answer("URL должен начинаться с http:// или https://")
        return

    streams = _load_streams()
    streams[slot - 1]["url"] = url
    _save_streams(streams)
    await message.answer(f"Окно {slot} обновлено.")


async def cmd_settitle(message: Message) -> None:
    if not _is_admin(message):
        await message.answer("Эта команда только для админа.")
        return

    text = (message.text or "").strip()
    parts = text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer(
            "Используй формат:\n"
            "/settitle <номер 1-4> <название>\n\n"
            "Пример:\n"
            "/settitle 2 Лига Европы: Матч 2"
        )
        return

    slot_raw, title = parts[1].strip(), parts[2].strip()
    if not slot_raw.isdigit():
        await message.answer("Номер окна должен быть числом от 1 до 4.")
        return

    slot = int(slot_raw)
    if slot < 1 or slot > 4:
        await message.answer("Номер окна должен быть от 1 до 4.")
        return

    if not title:
        await message.answer("Название не должно быть пустым.")
        return

    streams = _load_streams()
    streams[slot - 1]["title"] = title
    _save_streams(streams)
    await message.answer(f"Название для окна {slot} обновлено.")


async def cmd_streams(message: Message) -> None:
    if not _is_admin(message):
        await message.answer("Эта команда только для админа.")
        return

    streams = _load_streams()
    lines = ["Текущие ссылки:"]
    for i, stream in enumerate(streams, start=1):
        title = stream["title"] or f"Матч {i}"
        url = stream["url"] or "(пусто)"
        lines.append(f"{i}. {title}\n{url}")
    await message.answer("\n".join(lines))


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
    await message.answer(text, reply_markup=main_menu_kb(settings.webapp_url))


async def cmd_help(message: Message) -> None:
    settings = load_settings()
    await message.answer(
        "Команды:\n"
        "/start — меню\n"
        "/help — эта справка\n\n"
        "**Как пользоваться:** напиши любой вопрос по бизнесу одним сообщением.\n\n"
        "**Настройка ИИ:** в `.env` задай `OPENAI_API_KEY`, при необходимости "
        "`OPENAI_BASE_URL` (для совместимых API) и `OPENAI_MODEL`.\n\n"
        "**Админ (трансляции в Mini App, если используешь):**\n"
        "/setstream, /settitle, /streams",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(settings.webapp_url),
    )


async def ai_reply(message: Message, bot: Bot) -> None:
    if not message.text or not message.text.strip():
        return
    settings = load_settings()
    if not settings.openai_api_key:
        await message.answer(
            "Ключ ИИ не настроен. Добавь в `.env` строку:\n"
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
        settings = load_settings()
        await callback.message.edit_text(
            "Главное меню. Напиши вопрос по бизнесу в чат или нажми «Примеры».",
            reply_markup=main_menu_kb(settings.webapp_url),
        )
        await callback.answer()
        return

    if action == "about":
        settings = load_settings()
        await callback.message.edit_text(
            "Я помогаю самозанятым и малому бизнесу:\n"
            "• тексты постов и ответы клиентам\n"
            "• офферы и акции\n"
            "• идеи продвижения\n"
            "• цена и позиционирование (общие советы)\n"
            "• порядок действий без «магии»\n\n"
            "Пиши вопрос обычным сообщением — отвечу по существу.",
            reply_markup=main_menu_kb(settings.webapp_url),
        )
        await callback.answer()
        return

    if action == "examples":
        settings = load_settings()
        await callback.message.edit_text(
            "Примеры вопросов (скопируй и отправь):\n\n"
            "• У меня салон красоты в Алматы, 2 мастера. Как привлечь клиентов в Instagram за месяц?\n"
            "• Напиши короткий текст поста про скидку 20% на первую запись, тон дружелюбный.\n"
            "• Клиент просит скидку 30%, как ответить вежливо и удержать маржу?\n"
            "• Я делаю сайты на Tilda, как сформулировать оффер для локального бизнеса?\n\n"
            "Добавь своё: город, ниша, средний чек — ответ будет точнее.",
            reply_markup=main_menu_kb(settings.webapp_url),
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
    dp.message.register(cmd_setstream, Command("setstream"))
    dp.message.register(cmd_settitle, Command("settitle"))
    dp.message.register(cmd_streams, Command("streams"))
    dp.callback_query.register(menu_router, F.data.startswith("menu:"))
    # Обычный текст -> ИИ (после всех команд)
    dp.message.register(ai_reply, F.text & ~F.text.startswith("/"))

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

