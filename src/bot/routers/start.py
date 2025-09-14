from __future__ import annotations

import asyncio
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, FSInputFile

from ...i18n.texts import t
from ...keyboards import main_menu
from ..utils import user_lang, lang_kbd
from ...container import container

router = Router()

user_lang_repo = container.user_language_repository()
about_repo = container.about_repository()
metrics = container.metrics_service()
executor = container.executor()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    uid = message.from_user.id if message and message.from_user else None
    if uid:
        try:
            u = message.from_user
            loop = asyncio.get_running_loop()
            # Fire-and-forget metrics recording in thread pool
            loop.run_in_executor(
                executor,
                metrics.record_start,
                uid,
                getattr(u, "language_code", None),
                getattr(u, "username", None),
                getattr(u, "first_name", None),
                getattr(u, "last_name", None),
            )
        except Exception:
            pass
    saved = (await asyncio.get_running_loop().run_in_executor(executor, user_lang_repo.get_sync, uid)) if uid else None
    if not saved:
        await message.answer(t("ru", "lang.choose"), reply_markup=lang_kbd())
        return
    lang = user_lang(message)
    await message.answer(t(lang, "start.welcome"), reply_markup=main_menu(lang))


@router.callback_query(F.data.startswith("setlang:"))
async def set_language(cb: CallbackQuery) -> None:
    val = cb.data.split(":", 1)[1]
    if val not in ("ru", "en"):
        await cb.answer("Unknown language", show_alert=True)
        return
    await user_lang_repo.set(cb.from_user.id, val)
    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(executor, metrics.record_interaction, cb.from_user.id, "feature:set_language")
    except Exception:
        pass
    # Send a single welcome message with main menu to avoid duplicate greetings
    await cb.message.answer(t(val, "start.welcome"), reply_markup=main_menu(val))
    await cb.answer()


@router.message(Command("language"))
async def cmd_language(message: Message) -> None:
    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(executor, metrics.record_interaction, message.from_user.id, "command:/language")
    except Exception:
        pass
    await message.answer(t("ru", "lang.choose"), reply_markup=lang_kbd())


@router.message(F.text.in_({"О специалисте", "About"}))
async def about_handler(message: Message) -> None:
    lang = user_lang(message)
    loop = asyncio.get_running_loop()
    photo_path = await loop.run_in_executor(executor, about_repo.get_photo_file_path_sync)
    about_text = t(lang, "about.text")

    # First send the text message
    await message.answer(about_text)

    # Then, if available, send the photo as a separate message (no caption)
    if photo_path:
        await message.answer_photo(FSInputFile(photo_path))
