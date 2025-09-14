from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ...config import settings
from ...i18n.texts import t
from ...container import container
from ..utils import user_lang
calendar = container.calendar_service()

router = Router()

event_repo = container.event_repository()


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_list


@router.message(Command("admin"))
async def admin_help(message: Message) -> None:
    lang = user_lang(message)
    if not is_admin(message.from_user.id):
        await message.answer(t(lang, "admin.no_access"))
        return
    await message.answer(t(lang, "admin.help"))


@router.message(Command("admin_bookings"))
async def admin_bookings(message: Message) -> None:
    lang = user_lang(message)
    if not is_admin(message.from_user.id):
        await message.answer(t(lang, "admin.no_access"))
        return
    bookings = calendar.list_all_bookings()
    if not bookings:
        await message.answer("No bookings")
        return
    lines = []
    for b in bookings:
        lines.append(f"{b['id']} | {b['start']} | {b['session_type']} | {b['status']}")
    await message.answer("\n".join(lines))


@router.message(Command("admin_poster"))
async def admin_poster(message: Message) -> None:
    lang = user_lang(message)
    if not is_admin(message.from_user.id):
        await message.answer(t(lang, "admin.no_access"))
        return
    poster = await event_repo.get_all()
    if not poster:
        await message.answer("Poster empty")
        return
    lines = []
    for i in poster:
        try:
            when_str = i.when.strftime("%Y-%m-%d %H:%M")
        except Exception:
            when_str = str(getattr(i, 'when', ''))
        lines.append(f"{getattr(i, 'id', '')}: {getattr(i, 'title', '')} @ {when_str} ({getattr(i, 'place', '')})")
    await message.answer("\n".join(lines))
