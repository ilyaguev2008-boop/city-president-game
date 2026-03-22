"""Кэш вызова get_me — при многих каналах/джобах не дёргаем Telegram лишний раз."""

from __future__ import annotations

import asyncio
import time

from aiogram import Bot

_lock = asyncio.Lock()
_cached_id: int | None = None
_cached_at: float = 0.0
_TTL_SEC = 120.0


async def get_bot_user_id(bot: Bot) -> int:
    """ID бота с TTL-кэшем (безопасно при конкурентных вызовах)."""
    global _cached_id, _cached_at
    now = time.monotonic()
    if _cached_id is not None and (now - _cached_at) < _TTL_SEC:
        return _cached_id
    async with _lock:
        now = time.monotonic()
        if _cached_id is not None and (now - _cached_at) < _TTL_SEC:
            return _cached_id
        me = await bot.get_me()
        _cached_id = me.id
        _cached_at = now
        return _cached_id
