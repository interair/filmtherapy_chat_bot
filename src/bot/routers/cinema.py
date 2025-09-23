from __future__ import annotations

from pathlib import Path

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, InputMediaPhoto

from ..utils import user_lang, ik_kbd
from ...container import container
from ...i18n.texts import t
from ...services.storage import DATA_DIR
from ...keyboards import cinema_menu

router = Router()


# Main Film club button -> show submenu
@router.message(F.text.in_({"Киноклуб", "Film club", "🎬 Киноклуб", "🎬 Film club"}))
async def film_club_menu(message: Message) -> None:
    lang = user_lang(message)
    title = ("🎬 " + t(lang, "menu.cinema")) if (lang or "ru").startswith("ru") else ("🎬 " + t(lang, "menu.cinema"))
    await message.answer(title, reply_markup=cinema_menu(lang))


# Schedule button -> previous behavior
@router.message(F.text.in_({"Расписание", "🗓️ Расписание", "Schedule", "🗓️ Schedule"}))
async def film_club_schedule(message: Message) -> None:
    lang = user_lang(message)
    poster = await container.event_repository().get_upcoming()
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


# About Film club -> send text + media group
@router.message(F.text.in_({"О киноклубе", "ℹ️ О киноклубе", "About the Film Club", "ℹ️ About the Film Club"}))
async def film_club_about(message: Message) -> None:
    lang = user_lang(message)
    # First send the about text (editable via /i18n)
    about_text = t(lang, "cinema.about_text")
    await message.answer(about_text)

    # Then send photo group (0..many)
    try:
        items = container.about_repository().list_cinema_photos()
    except Exception:
        items = []
    media = []
    for fn in items[:10]:  # Telegram limit per media group
        p = Path(DATA_DIR) / fn
        if p.exists():
            try:
                media.append(InputMediaPhoto(media=FSInputFile(str(p))))
            except Exception:
                continue
    if media:
        try:
            await message.answer_media_group(media)
        except Exception:
            # Fallback: send sequentially if media group fails
            for m in media:
                try:
                    await message.answer_photo(m.media)  # type: ignore[arg-type]
                except Exception:
                    continue


@router.callback_query(F.data == "cinema:about")
async def cb_cinema_about(cb: CallbackQuery) -> None:
    lang = user_lang(cb)
    about_text = t(lang, "cinema.about_text")
    # Send text first
    await cb.message.answer(about_text)
    # Then photos (if any)
    try:
        items = container.about_repository().list_cinema_photos()
    except Exception:
        items = []
    media = []
    for fn in items[:10]:
        p = Path(DATA_DIR) / fn
        if p.exists():
            try:
                media.append(InputMediaPhoto(media=FSInputFile(str(p))))
            except Exception:
                continue
    if media:
        try:
            await cb.message.answer_media_group(media)
        except Exception:
            for m in media:
                try:
                    await cb.message.answer_photo(m.media)  # type: ignore[arg-type]
                except Exception:
                    continue
    await cb.answer()


@router.callback_query(F.data == "cinema:schedule")
async def cb_cinema_schedule(cb: CallbackQuery) -> None:
    lang = user_lang(cb)
    poster = await container.event_repository().get_upcoming()
    if not poster:
        await cb.message.answer(t(lang, "cinema.poster"))
        await cb.answer()
        return
    for item in poster:
        try:
            when_str = item.when.strftime("%Y-%m-%d %H:%M")
        except Exception:
            when_str = str(getattr(item, 'when', ''))
        price = getattr(item, 'price', None)
        price_str = f"{price}€" if price is not None else t(lang, "free") if callable(t) else "Free"
        text = f"<b>{getattr(item, 'title', '')}</b>\n{when_str}\n{getattr(item, 'place', '')}\nЦена: {price_str}"
        desc = getattr(item, 'description', None)
        if desc:
            try:
                d = str(desc).strip()
            except Exception:
                d = None
            if d:
                text = f"{text}\n\n{d}"
        if len(text) > 1024:
            text = text[:1021] + "..."
        kbd = ik_kbd([[ ("📝 " + t(lang, "cinema.register"), f"reg:{getattr(item, 'id', '')}") ]])
        photo_name = getattr(item, 'photo', None)
        if photo_name:
            photo_path = Path(DATA_DIR) / str(photo_name)
            if photo_path.exists():
                try:
                    await cb.message.answer_photo(photo=FSInputFile(str(photo_path)), caption=text, reply_markup=kbd)
                    continue
                except Exception:
                    pass
        await cb.message.answer(text, reply_markup=kbd)
    await cb.answer()


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
        exists = await container.event_registration_repository().get_one(event_id, uid)
        if exists:
            msg = t(lang, "cinema.already_registered")
        else:
            await container.event_registration_repository().add(event_id, uid, name)
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
        ev = await container.event_repository().get_by_id(event_id) if event_id else None
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
        await container.event_registration_repository().delete(event_id, uid)
        try:
            await cb.message.edit_text(t(lang, "cinema.canceled"))
        except Exception:
            await cb.message.answer(t(lang, "cinema.canceled"))
        await cb.answer()
    except Exception:
        await cb.answer("Action failed", show_alert=True)
