from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone

from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from ..config import settings
from ..container import container


def safe_create_task(coro, **kwargs):
    """
    Wrap asyncio.create_task to be compatible across Python versions.
    Specifically handles 'eager_start' which is new in 3.14.
    """
    if sys.version_info < (3, 14):
        kwargs.pop("eager_start", None)
    return asyncio.create_task(coro, **kwargs)


async def user_lang(message: Message | CallbackQuery) -> str:
    try:
        uid = message.from_user.id if message and message.from_user else None
        if uid:
            pref = await container.user_language_repository().get(uid)
            if pref:
                return pref
        return (message.from_user.language_code or settings.default_lang) if message and message.from_user else settings.default_lang
    except Exception:
        return settings.default_lang


def ik_kbd(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=data) for text, data in row] for row in rows]
    )


def lang_kbd() -> InlineKeyboardMarkup:
    return ik_kbd([
        [("Русский", "setlang:ru"), ("English", "setlang:en")]
    ])

