from __future__ import annotations

import json
import logging
import re
from typing import Any

import aiohttp

from text_utils import (
    clean_title_for_post,
    normalize_cyrillic_news_prose,
    sanitize_post_text,
    strip_urls,
)

logger = logging.getLogger(__name__)


def _parse_openai_error_body(raw: str) -> str:
    """Текст ошибки из JSON ответа OpenAI-совместимого API."""
    if not raw.strip():
        return "(пустой ответ)"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw.strip()[:400]
    err = data.get("error")
    if isinstance(err, dict):
        msg = err.get("message") or err.get("code") or str(err)
        typ = err.get("type") or err.get("param")
        if typ:
            return f"{msg} ({typ})"[:400]
        return str(msg)[:400]
    if isinstance(err, str):
        return err[:400]
    return raw.strip()[:400]

NEWS_REWRITE_SYSTEM_RU = """Ты редактор новостей для Telegram-канала.

Перескажи материал на русском для поста в духе сильного спортивного Telegram: плотно, по делу, без воды.

Правила языка:
- Пиши только кириллицей. Латиницей — имена собственные (игроки, тренеры, клубы, лиги, спонсоры, бренды,
  города, стадионы), общепринятые аббревиатуры (ФИФА, UEFA, VAR и т.п.). Всё остальное — по-русски.
- Любой английский из источника (включая слоганы вроде «Here we go again», подписи к фото, заголовки)
  переводи на русский по смыслу; не оставляй английские фразы «для красоты».
- Не вставляй английские служебные слова (the, and, report, news как обычные слова) — замени русскими.

Стиль как в качественных футбольных каналах (ориентир — живой пост, не сухая лента):
- Длина по сути материала: от одной-двух коротких строк-«ударов» до нескольких абзацев с цифрами и контекстом,
  если в источнике есть разбор или статистика. Не раздувай короткую новость до колонки.
- Первая строка может быть очень короткой (как подпись к картинке: наблюдение, ирония, акцент).
- Эмодзи — умеренно и только если усиливают смысл: не больше одного в первой строке и не больше 2–3 на весь пост.
  Смысловые варианты: 👀 — наблюдение/факт; 🗣️ — прямая речь или цитата; 🗞️ — аналитика, обзор, «мысли».
  Не забивай текст эмодзи в каждом предложении.
- Прямую речь или цитату игрока/тренера можно оформить так: строка «🗣️ Имя Фамилия:» (или кириллическая
  форма имени), затем абзац с цитатой в кавычках «…».
- Развёрнутый аналитический заголовок в духе «Мысли о важном» — только если в источнике реально есть
  аналитика или позиция; не выдумывай рубрику ради вида.
- Без хэштегов и без заголовков уровня Markdown (#).

Факты и тон:
- Не выдумывай факты, счёт, имена и цифры; если чего-то нет в тексте — не дополняй.
- Сохраняй нейтральный или слегка оценочный тон, уместный для спортивной редакции (без токсичности и мата).
- Убери призывы подписаться, рекламу, «читайте также», хлебные крошки, служебный мусор СМИ.
- Не вставляй ссылки, URL и фразы вроде «читайте по ссылке»."""

POLISH_ENGLISH_TO_RUSSIAN_SYSTEM_RU = """Ты редактор новостей для Telegram-канала.

Перед тобой готовый текст поста на русском (возможны хвосты английского или латинские слоганы). Задача:
- Замени все оставшиеся английские слова и фразы на русские; слоганы и подписи вроде «Here we go again»
  переведи по смыслу, не оставляй английский в посте.
- Имена собственные не переводить: игроки, клубы, бренды, лиги, города в латинице как в тексте, аббревиатуры.
- Не меняй смысл, факты, счёт, порядок абзацев. Уместные эмодзи в начале строк (👀 🗣️ 🗞️) не удаляй и не
  плоди новые. Ссылки не добавляй.
- Верни только итоговый текст поста, без комментариев."""


def _text_needs_english_polish(text: str) -> bool:
    """Есть ли латинские буквы (возможный непереведённый английский)."""
    return bool(re.search(r"[A-Za-z]", text)) if text else False


async def polish_english_to_russian_ru(
    *,
    api_key: str,
    base_url: str,
    model: str,
    text: str,
    timeout_sec: int = 60,
) -> str:
    """Второй проход: перевод оставшегося английского, имена собственные сохраняются."""
    t = (text or "").strip()
    if not t:
        return ""
    return await complete_chat(
        api_key=api_key,
        base_url=base_url,
        model=model,
        user_text=t,
        timeout_sec=timeout_sec,
        system_prompt=POLISH_ENGLISH_TO_RUSSIAN_SYSTEM_RU,
    )

SYSTEM_PROMPT_RU = """Ты дружелюбный AI-помощник для владельцев Telegram-каналов, которые используют бота автопостинга из своих источников новостей.

Помогаешь с: подключением бота к каналу, правами администратора, поиском ленты новостей на сайтах СМИ, настройкой сценариев постинга, пониманием работы разделов «Мои каналы», «Источники новостей», «Черновики».

Правила:
- Отвечай на русском, кратко и по делу, списками где уместно.
- Если не хватает контекста — задай 1–3 уточняющих вопроса.
- Не обещай обход правил Telegram и сайтов; про авторские права на контент источников — кратко и нейтрально, без юридических гарантий.
"""


async def complete_chat(
    *,
    api_key: str,
    base_url: str,
    model: str,
    user_text: str,
    timeout_sec: int = 90,
    system_prompt: str | None = None,
) -> str:
    """Вызывает Chat Completions API (OpenAI или совместимый сервер)."""
    url = base_url.rstrip("/") + "/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    system = system_prompt or SYSTEM_PROMPT_RU
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.7,
        "max_tokens": 2000,
    }

    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                raw = await resp.text()
                if resp.status != 200:
                    detail = _parse_openai_error_body(raw)
                    logger.warning(
                        "Chat API HTTP %s %s: %s",
                        resp.status,
                        url,
                        raw[:800],
                    )
                    raise RuntimeError(f"HTTP {resp.status}: {detail}")

                try:
                    data = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"Некорректный JSON от API: {raw[:200]}") from exc
                choices = data.get("choices")
                if not choices:
                    raise RuntimeError(f"Нет choices в ответе: {raw[:300]}")
                message = choices[0].get("message") or {}
                content = message.get("content")
                if not content:
                    # Некоторые модели отдают refusal / tool_calls
                    if message.get("refusal"):
                        raise RuntimeError(f"Модель отказалась: {message.get('refusal')}")
                    raise RuntimeError("Нет текста в ответе")
                return str(content).strip()
    except aiohttp.ClientError as exc:
        logger.warning("Сеть при запросе к ИИ: %s", exc)
        raise RuntimeError(f"Сеть: {exc}") from exc


async def rewrite_news_ru(
    *,
    api_key: str,
    base_url: str,
    model: str,
    title: str,
    body: str,
    timeout_sec: int = 90,
    polish_english_translation: bool = True,
) -> str:
    """Пересказ новости на русском для поста (без ссылок в тексте на стороне модели)."""
    title = clean_title_for_post(title)
    body = sanitize_post_text(strip_urls(body))[:12000]
    user_text = f"Заголовок:\n{title}\n\nТекст:\n{body}"
    raw = await complete_chat(
        api_key=api_key,
        base_url=base_url,
        model=model,
        user_text=user_text,
        timeout_sec=timeout_sec,
        system_prompt=NEWS_REWRITE_SYSTEM_RU,
    )
    out = sanitize_post_text(raw)
    out = normalize_cyrillic_news_prose(out)
    if polish_english_translation and _text_needs_english_polish(out):
        try:
            polished = await polish_english_to_russian_ru(
                api_key=api_key,
                base_url=base_url,
                model=model,
                text=out,
                timeout_sec=min(90, timeout_sec + 20),
            )
            out = sanitize_post_text(polished)
            out = normalize_cyrillic_news_prose(out)
        except Exception:
            logger.warning("ИИ: не удалось довести перевод английского", exc_info=True)
    return out


def split_for_telegram(text: str, max_len: int = 4000) -> list[str]:
    """Делит длинный текст на части под лимит Telegram (4096)."""
    text = text.strip()
    if len(text) <= max_len:
        return [text] if text else []

    parts: list[str] = []
    rest = text
    while rest:
        chunk = rest[:max_len]
        if len(rest) > max_len:
            cut = chunk.rfind("\n")
            if cut > max_len // 2:
                chunk = rest[: cut + 1]
        parts.append(chunk.rstrip())
        rest = rest[len(chunk) :].lstrip()
    return parts
