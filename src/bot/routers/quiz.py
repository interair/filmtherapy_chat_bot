from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from ..utils import user_lang, ik_kbd
from ...container import container
from ...i18n.texts import t

router = Router()


class QuizStates(StatesGroup):
    choosing_mood = State()
    choosing_company = State()


@router.message(F.text.in_({"Что посмотреть?", "What to watch?", "🎥 Что посмотреть?", "🎥 What to watch?"}))
async def quiz_start(message: Message, state: FSMContext) -> None:
    lang = await user_lang(message)
    cfg = await container.quiz_repository().get_config()
    moods = [(m.get("title", ""), m.get("code", "")) for m in cfg.get("moods", [])]
    rows = [[(title, f"mood:{code}")] for title, code in moods if title and code]
    await state.set_state(QuizStates.choosing_mood)
    await message.answer(t(lang, "quiz.mood"), reply_markup=ik_kbd(rows))


@router.callback_query(F.data.startswith("mood:"))
async def quiz_mood(cb: CallbackQuery, state: FSMContext) -> None:
    lang = await user_lang(cb)
    code = cb.data.split(":", 1)[1]
    await state.update_data(mood=code)
    await state.set_state(QuizStates.choosing_company)
    cfg = await container.quiz_repository().get_config()
    companies = [(c.get("title", ""), c.get("code", "")) for c in cfg.get("companies", [])]
    rows = [[(title, f"company:{code}:{cc}")] for title, cc in companies if title and cc]
    try:
        await cb.message.edit_text(t(lang, "quiz.company"), reply_markup=ik_kbd(rows))
    except Exception:
        await cb.message.answer(t(lang, "quiz.company"), reply_markup=ik_kbd(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("company:"))
async def quiz_company(cb: CallbackQuery, state: FSMContext) -> None:
    lang = await user_lang(cb)
    _, mood_code, comp_code = cb.data.split(":", 2)
    cfg = await container.quiz_repository().get_config()
    recs = cfg.get("recs", {})
    key = f"{mood_code}|{comp_code}"
    movies = recs.get(key) or ["Inception", "Amélie", "Interstellar"]
    await cb.message.edit_text(f"{t(lang, 'quiz.result')}\n- " + "\n- ".join(movies))
    # Clear quiz state after completion
    await state.clear()
    await cb.answer()
