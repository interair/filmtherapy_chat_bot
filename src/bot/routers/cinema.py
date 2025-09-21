from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from pathlib import Path

from ...i18n.texts import t
from ...container import container
from ...services.storage import DATA_DIR
from ..utils import user_lang, ik_kbd

router = Router()

event_repo = container.event_repository()
reg_repo = container.event_registration_repository()


@router.message(F.text.in_({"Киноклуб", "Film club", "🎬 Киноклуб", "🎬 Film club"}))
async def film_club(message: Message) -> None:
    lang = user_lang(message)
    poster = await event_repo.get_upcoming()
    if not poster:
        await message.answer(t(lang, "cinema.poster"))
        return
    for item in poster:
        try:
            when_str = item.when.strftime("%Y-%m-%d %H:%M")
        except Exception:
            when_str = str(getattr(item, 'when', ''))
        price = getattr(item, 'price', None)
        price_str = f"{price}€" if price is not None else t(lang, "free") if callable(t) else "Free"
        text = f"<b>{getattr(item, 'title', '')}</b>\n{when_str}\n{getattr(item, 'place', '')}\nЦена: {price_str}"
        
        # Append optional description from Events (web) if present
        desc = getattr(item, 'description', None)
        if desc:
            # Ensure description is a string and strip excessive whitespace
            try:
                d = str(desc).strip()
            except Exception:
                d = None
            if d:
                text = f"{text}\n\n{d}"
        
        # Truncate caption if it's too long (Telegram limit is 1024 characters)
        if len(text) > 1024:
            text = text[:1021] + "..."
            
        kbd = ik_kbd([[("📝 " + t(lang, "cinema.register"), f"reg:{getattr(item, 'id', '')}")]])
        photo_name = getattr(item, 'photo', None)
        if photo_name:
            photo_path = Path(DATA_DIR) / str(photo_name)
            if photo_path.exists():
                try:
                    await message.answer_photo(photo=FSInputFile(str(photo_path)), caption=text, reply_markup=kbd)
                    continue
                except Exception:
                    pass
        await message.answer(text, reply_markup=kbd)


@router.callback_query(F.data.startswith("reg:"))
async def register_film(cb: CallbackQuery) -> None:
    lang = user_lang(cb)
    event_id = cb.data.split(":", 1)[1]
    uid = cb.from_user.id if cb and cb.from_user else None
    name = cb.from_user.full_name if cb and cb.from_user else ""
    if not uid:
        await cb.answer("Invalid user", show_alert=True)
        return
    try:
        exists = await reg_repo.get_one(event_id, uid)
        if exists:
            msg = t(lang, "cinema.already_registered")
        else:
            await reg_repo.add(event_id, uid, name)
            msg = t(lang, "cinema.registered")
        kbd = ik_kbd([[ 
            ("💳 " + t(lang, "book.pay_button"), f"pay_event:{event_id}"),
            ("❌ " + t(lang, "book.cancel_button"), f"cancel_event:{event_id}")
        ]])
        try:
            await cb.message.edit_text(msg, reply_markup=kbd)
        except Exception:
            await cb.message.answer(msg, reply_markup=kbd)
        await cb.answer()
    except Exception:
        await cb.answer("Action failed", show_alert=True)


@router.callback_query(F.data.startswith("pay_event:"))
async def pay_event(cb: CallbackQuery) -> None:
    lang = user_lang(cb)
    event_id = cb.data.split(":", 1)[1] if isinstance(cb.data, str) else ""
    # Resolve event price or fallback to i18n-configured cinema price
    price_val: float | None = None
    try:
        ev = await event_repo.get_by_id(event_id) if event_id else None
        if ev and getattr(ev, "price", None) is not None:
            price_val = float(getattr(ev, "price"))
    except Exception:
        ev = None
    if price_val is None:
        try:
            p_str = (t(lang, "price.cinema") or "90").strip()
        except Exception:
            p_str = "90"
        try:
            price_val = float(p_str.replace(",", "."))
        except Exception:
            price_val = 90.0
    # Choose per-type message text for cinema
    try:
        msg_text = (t(lang, "book.payment_link.cinema") or "").strip()
        if not msg_text or msg_text == "book.payment_link.cinema":
            msg_text = t(lang, "book.payment_link")
    except Exception:
        msg_text = t(lang, "book.payment_link")
    # URL handling
    try:
        url = (t(lang, "book.payment_url") or "").strip()
    except Exception:
        url = ""
    if url and url != "book.payment_url":
        label = "Цена" if (lang or "ru").startswith("ru") else "Price"
        price_str = f"{int(price_val) if float(price_val).is_integer() else price_val}€"
        text = f"{msg_text}\n{label}: {price_str}\n{url}"
        try:
            await cb.message.answer(text, disable_web_page_preview=True)
        except Exception:
            await cb.message.answer(text)
        await cb.answer()
    else:
        await cb.answer(t(lang, "book.pay_unavailable"), show_alert=True)


@router.callback_query(F.data.startswith("cancel_event:"))
async def cancel_event(cb: CallbackQuery) -> None:
    lang = user_lang(cb)
    event_id = cb.data.split(":", 1)[1]
    uid = cb.from_user.id if cb and cb.from_user else None
    if not uid:
        await cb.answer("Invalid user", show_alert=True)
        return
    try:
        await reg_repo.delete(event_id, uid)
        try:
            await cb.message.edit_text(t(lang, "cinema.canceled"))
        except Exception:
            await cb.message.answer(t(lang, "cinema.canceled"))
        await cb.answer()
    except Exception:
        await cb.answer("Action failed", show_alert=True)
