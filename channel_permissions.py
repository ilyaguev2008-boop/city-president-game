"""Проверка прав бота на публикацию в канале.

В ответе getChatMember у ChatMemberAdministrator поле can_post_messages может быть None
(поле опционально в Bot API). Старый код делал bool(None) == False и ошибочно блокировал пост.
"""

from __future__ import annotations

from aiogram.types import ChatMemberAdministrator, ChatMemberOwner


def bot_can_post_to_channel(member: object) -> bool:
    """True, если боту разумно разрешить попытку send_message в канал."""
    if isinstance(member, ChatMemberOwner):
        return True
    if isinstance(member, ChatMemberAdministrator):
        cap = member.can_post_messages
        if cap is True:
            return True
        if cap is False:
            return False
        # None — Telegram не прислал поле; не блокируем (ошибку покажет send_message)
        return True
    return bool(getattr(member, "can_post_messages", False))
