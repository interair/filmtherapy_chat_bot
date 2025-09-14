from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from ...i18n.texts import t
from ...container import container
from ..utils import user_lang, ik_kbd

router = Router()

quiz_repo = container.quiz_repository()


@router.message(F.text.in_({"Что посмотреть?", "What to watch?"}))
async def quiz_start(message: Message) -> None:
    lang = user_lang(message)
    cfg = await quiz_repo.get_config()
    moods = [(m.get("title", ""), m.get("code", "")) for m in cfg.get("moods", [])]
    rows = [[(title, f"mood:{code}")] for title, code in moods if title and code]
    await message.answer(t(lang, "quiz.mood"), reply_markup=ik_kbd(rows))


@router.callback_query(F.data.startswith("mood:"))
async def quiz_mood(cb: CallbackQuery) -> None:
    lang = user_lang(cb)
    code = cb.data.split(":", 1)[1]
    cfg = await quiz_repo.get_config()
    companies = [(c.get("title", ""), c.get("code", "")) for c in cfg.get("companies", [])]
    rows = [[(title, f"company:{code}:{cc}")] for title, cc in companies if title and cc]
    await cb.message.edit_text(t(lang, "quiz.company"), reply_markup=ik_kbd(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("company:"))
async def quiz_company(cb: CallbackQuery) -> None:
    lang = user_lang(cb)
    _, mood_code, comp_code = cb.data.split(":", 2)
    cfg = await quiz_repo.get_config()
    recs = cfg.get("recs", {})
    key = f"{mood_code}|{comp_code}"
    movies = recs.get(key) or ["Inception", "Amélie", "Interstellar"]
    await cb.message.edit_text(f"{t(lang, 'quiz.result')}\n- " + "\n- ".join(movies))
    await cb.answer()
