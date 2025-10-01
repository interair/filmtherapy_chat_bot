from __future__ import annotations

import contextlib
import logging
from datetime import datetime, timezone, timedelta

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from ..booking_flow import BookingData
from ..callbacks import encode_stype, encode_loc, decode_stype, decode_loc
from ..utils import user_lang, ik_kbd
from ...container import container
from ...exceptions import ValidationError
from ...i18n.texts import t

logger = logging.getLogger(__name__)

router = Router()


# Centralized constants and helpers
SESSION_TYPES = ("Песочная терапия", "Очно", "Онлайн")
PAGE_SIZE = 7

def _stype_label(stype: str) -> str:
    s = (stype or "").strip()
    if s == "Онлайн" or s.lower() == "online":
        return f"💻 {s}"
    if s == "Песочная терапия" or ("песоч" in s.lower() or "sand" in s.lower()):
        return f"🏖️ {s}"
    return f"🏠 {s}"

def _stype_suffix(stype: str | None) -> str:
    s = (stype or "").strip()
    s_low = s.lower()
    if s == "Онлайн" or s_low == "online":
        return "online"
    if s == "Песочная терапия" or "песоч" in s_low or "sand" in s_low:
        return "sand"
    return "offline"

def _num_price(val: str | float | int, default: float = 90.0) -> float:
    try:
        if isinstance(val, (int, float)):
            return float(val)
        return float(str(val).replace(",", ".").strip())
    except (ValueError, TypeError) as e:
        logger.debug("Failed to parse price value %s, using default %s: %s", val, default, e)
        return float(default)

def _get_price(lang: str | None, suffix: str) -> float:
    try:
        price_str = (t(lang, f"price.{suffix}") or "90").strip()
    except Exception:
        price_str = "90"
    return _num_price(price_str)

def _payment_message_text(lang: str | None, suffix: str, price: float) -> tuple[str | None, str | None]:
    # Returns (text, url) if available, otherwise (None, None)
    try:
        msg_text = (t(lang, f"book.payment_link.{suffix}") or "").strip()
        if not msg_text or msg_text == f"book.payment_link.{suffix}":
            msg_text = t(lang, "book.payment_link")
    except Exception as e:
        logger.debug("Failed to get payment message text for suffix=%s: %s", suffix, e)
        msg_text = t(lang, "book.payment_link")
    try:
        url = (t(lang, "book.payment_url") or "").strip()
    except Exception:
        url = ""
    if not url or url == "book.payment_url":
        return None, None
    price_label = "Цена" if (lang or "ru").startswith("ru") else "Price"
    price_str = f"{int(price) if float(price).is_integer() else price}€"
    return f"{msg_text}\n{price_label}: {price_str}\n{url}", url

# --- Google Calendar link builder -----------------------------------
from urllib.parse import urlencode, quote_plus

def _fmt_gcal_datetime(dt: datetime) -> str:
    # Ensure UTC and format as YYYYMMDDTHHMMSSZ
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y%m%dT%H%M%SZ")

def _build_gcal_link_from_booking(booking: dict, lang: str | None) -> str | None:
    if not isinstance(booking, dict):
        return None
    try:
        s_s = booking.get("start")
        e_s = booking.get("end")
        if not isinstance(s_s, str):
            return None
        from_iso = datetime.fromisoformat
        start_dt = from_iso(s_s.replace("Z", "+00:00"))
        if isinstance(e_s, str):
            end_dt = from_iso(e_s.replace("Z", "+00:00"))
        else:
            # fallback: +50 minutes
            end_dt = start_dt + timedelta(minutes=50)
    except (ValueError, TypeError, AttributeError) as e:
        logger.warning("Failed to parse booking dates for calendar link, booking_id=%s: %s", booking.get("id"), e)
        return None

    title_raw = booking.get("session_type") or "Consultation"
    title = title_raw
    loc = booking.get("location") or ("Online" if not (lang or "ru").startswith("ru") else "Онлайн")
    # Description can include booking id and a friendly note
    bid = booking.get("id") or ""
    who = booking.get("name") or ""
    descr_en = f"Booking ID: {bid}. Client: {who}."
    descr_ru = f"Номер брони: {bid}. Клиент: {who}."
    details = descr_ru if (lang or "ru").startswith("ru") else descr_en

    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{_fmt_gcal_datetime(start_dt)}/{_fmt_gcal_datetime(end_dt)}",
        "location": loc,
        "details": details,
        "ctz": "UTC",
    }
    return "https://calendar.google.com/calendar/render?" + urlencode(params, quote_via=quote_plus)

async def safe_cb_answer(cb: CallbackQuery, text: str | None = None, show_alert: bool = False) -> None:
    try:
        await cb.answer(text=text, show_alert=show_alert)
    except Exception:
        logger.debug("safe_cb_answer failed", exc_info=True)

async def send_or_edit(event: Message | CallbackQuery, text: str, reply_markup=None) -> None:
    # Prefer editing for callbacks; fall back to sending a new message
    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=reply_markup)
        except Exception:
            logger.debug("edit_text failed; falling back to answer", exc_info=True)
            try:
                await event.message.answer(text, reply_markup=reply_markup)
            except Exception:
                logger.exception("Failed to send answer after edit_text failure")
            await safe_cb_answer(event)
    else:
        await event.answer(text, reply_markup=reply_markup)

class BookingStates(StatesGroup):
    choosing_type = State()
    choosing_location = State()
    choosing_date = State()
    choosing_time = State()
    confirming = State()


@router.message(F.text.in_({"Записаться на консультацию", "Book a consultation", "🗓️ Записаться на консультацию", "🗓️ Book a consultation"}))
async def book_entry(message: Message, state: FSMContext) -> None:
    lang = user_lang(message)
    logger.info("Booking: entry user=%s", getattr(message.from_user, "id", None))
    types = SESSION_TYPES
    rows = [[(_stype_label(stype), f"type:{stype}")] for stype in types]
    await state.set_state(BookingStates.choosing_type)
    await message.answer(t(lang, "book.choose_type"), reply_markup=ik_kbd(rows))


@router.message(F.text.in_({"Онлайн-сессия", "Online session", "💻 Онлайн-сессия", "💻 Online session"}))
async def online_entry(message: Message, state: FSMContext) -> None:
    lang = user_lang(message)
    await state.set_state(BookingStates.choosing_type)
    await state.update_data(session_type="Онлайн", location=None)
    # Immediately go to dates for online sessions
    await show_dates(message, state)


@router.callback_query(F.data.startswith("type:"), BookingStates.choosing_type)
async def choose_type(cb: CallbackQuery, state: FSMContext) -> None:
    session_type = cb.data.split(":", 1)[1]
    await state.update_data(session_type=session_type)

    if session_type == "Онлайн":
        await state.update_data(location=None)
        await show_dates(cb, state)
    else:
        await show_locations(cb, state)


async def _get_locations_list(session_type: str | None) -> list[str]:
    # Try to use per-type mapping first
    try:
        if session_type:
            m = await container.session_locations_repository().get_map()
            arr = m.get(str(session_type).strip())
            if isinstance(arr, list) and len(arr) > 0:
                return [str(x) for x in arr]
    except Exception as e:
        logger.warning("Failed to fetch session-specific locations for type=%s: %s", session_type, e)
    # Fallback to all known locations from repo
    try:
        models = await container.location_repository().get_all()
        locs = [l.name for l in models]
        if locs:
            return locs
    except Exception as e:
        logger.warning("Failed to fetch all locations from repository: %s", e, exc_info=True)
    # Fallback to built-in defaults
    from ...services.calendar_service import LOCATIONS as DEFAULT_LOCS
    return list(DEFAULT_LOCS)


async def show_locations(cb: CallbackQuery, state: FSMContext):
    lang = user_lang(cb)
    data = await state.get_data()
    stype = data.get("session_type") if isinstance(data, dict) else None
    locs = await _get_locations_list(str(stype) if stype else None)
    rows = [[(loc, f"loc:{loc}")] for loc in locs]

    await state.set_state(BookingStates.choosing_location)
    await cb.message.edit_text(t(lang, "book.choose_location"), reply_markup=ik_kbd(rows))


@router.callback_query(F.data.startswith("loc:"), BookingStates.choosing_location)
async def choose_location(cb: CallbackQuery, state: FSMContext) -> None:
    location = cb.data.split(":", 1)[1]
    await state.update_data(location=location)
    await show_dates(cb, state)


PAGE_SIZE = 7


def _build_dates_rows(dates: list[str], page: int, stype_code: str, loc_code: str) -> list[list[tuple[str, str]]]:
    total = len(dates)
    if total == 0:
        return []
    page = max(0, page)
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    page_items = dates[start:end]
    # Include session/location codes into callback to make flow resilient to lost FSM state
    rows = [[(d, f"date:{stype_code}:{loc_code}:{d}")] for d in page_items]
    # Navigation row includes page index and codes
    prev_page = page - 1 if start > 0 else None
    next_page = page + 1 if end < total else None
    nav_row = []
    if prev_page is not None:
        nav_row.append(("←", f"dates:p:{stype_code}:{loc_code}:{prev_page}"))
    # Show simple page indicator like 1/5 as a noop
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    indicator = f"{page + 1}/{total_pages}"
    nav_row.append((indicator, "noop"))
    if next_page is not None:
        nav_row.append(("→", f"dates:p:{stype_code}:{loc_code}:{next_page}"))
    if nav_row:
        rows.append(nav_row)
    return rows


async def show_dates(event: Message | CallbackQuery, state: FSMContext):
    lang = user_lang(event)
    data = await state.get_data()

    session_type = data.get("session_type")
    location = data.get("location")

    dates = await container.booking_flow().get_available_dates(
        session_type,
        location,
    )

    if not dates:
        await send_or_edit(event, t(lang, "book.no_slots"))
        return

    # Cache dates and codes in FSM to avoid recomputation during pagination
    await state.update_data(_dates_cache=dates)
    st_code = encode_stype(session_type or "")
    loc_code = await encode_loc(location)
    rows = _build_dates_rows(dates, page=0, stype_code=st_code, loc_code=loc_code)
    await state.set_state(BookingStates.choosing_date)
    await send_or_edit(event, t(lang, "book.choose_date"), reply_markup=ik_kbd(rows))


@router.callback_query(F.data.startswith("dates:p:"))
async def paginate_dates(cb: CallbackQuery, state: FSMContext) -> None:
    # Expected format: dates:p:<stype_code>:<loc_code>:<page>
    parts = (cb.data or "").split(":")
    if len(parts) < 5:
        await safe_cb_answer(cb)
        return
    st_code = parts[2]
    loc_code = parts[3]
    try:
        page = int(parts[4])
    except (ValueError, TypeError) as e:
        logger.warning("Invalid page index in dates pagination: %r, error: %s", parts[4] if len(parts) > 4 else None, e)
        page = 0
    # Restore state if lost: decode stype/loc from codes
    try:
        session_type = decode_stype(st_code)
    except Exception as e:
        logger.warning("Failed to decode session type from code: %r, error: %s", st_code, e)
        session_type = None
    try:
        location = await decode_loc(loc_code)
    except Exception as e:
        logger.warning("Failed to decode location from code: %r, error: %s", loc_code, e)
        location = None
    if session_type is not None:
        await state.update_data(session_type=session_type)
    if location is not None or session_type == "Онлайн":
        # For online, force location=None
        await state.update_data(location=location if session_type != "Онлайн" else None)
    # Try to use cached dates, recompute on miss
    data = await state.get_data()
    dates = data.get("_dates_cache") if isinstance(data, dict) else None
    if not dates:
        try:
            dates = await container.booking_flow().get_available_dates(session_type, location)
        except Exception:
            logger.exception("Failed to recompute available dates for pagination")
            dates = []
    rows = _build_dates_rows(dates or [], page=page, stype_code=st_code, loc_code=loc_code)
    await state.set_state(BookingStates.choosing_date)
    try:
        await cb.message.edit_text(t(user_lang(cb), "book.choose_date"), reply_markup=ik_kbd(rows))
    except Exception:
        logger.debug("edit_text failed in paginate_dates; falling back to answer", exc_info=True)
        await cb.message.answer(t(user_lang(cb), "book.choose_date"), reply_markup=ik_kbd(rows))


@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery) -> None:
    # Do nothing, just silently acknowledge to avoid error popup
    try:
        await cb.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("date:"))
async def choose_date(cb: CallbackQuery, state: FSMContext) -> None:
    # Expected format: date:<stype_code>:<loc_code>:<dd-mm-yy>
    parts = (cb.data or "").split(":")
    if len(parts) < 4:
        with contextlib.suppress(Exception):
            await cb.answer()
        return
    st_code = parts[1]
    loc_code = parts[2]
    date = parts[3]
    try:
        session_type = decode_stype(st_code)
        location = await decode_loc(loc_code)
        await state.update_data(session_type=session_type, location=location)
    except Exception as e:
        logger.warning("Failed to decode session type or location, st_code=%s, loc_code=%s: %s", st_code, loc_code, e)
    logger.info("Booking: user %s chose date %s", getattr(cb.from_user, "id", None), date)
    await state.update_data(date=date)
    with contextlib.suppress(Exception):
        await cb.answer()
    await show_times(cb, state)


async def show_times(cb: CallbackQuery, state: FSMContext):
    lang = user_lang(cb)
    data = await state.get_data()
    date = data.get("date")
    stype = data.get("session_type")
    loc = data.get("location")

    # Guard against missing state (can happen in stateless webhook environments)
    if not date or not stype:
        try:
            await cb.message.answer(t(lang, "book.no_slots"))
        except Exception:
            pass
        with contextlib.suppress(Exception):
            await cb.answer()
        return

    try:
        logger.info("Booking: fetching times for user=%s date=%s type=%s loc=%s", getattr(cb.from_user, "id", None), date, stype, loc)
        slots = await container.booking_flow().get_available_times(date, stype, loc)
        logger.info("Booking: found %s slots for date=%s", len(slots) if slots is not None else 0, date)
    except Exception:
        logger.exception("Booking: failed to fetch times for date=%s", date)
        try:
            await cb.answer(t(lang, "book.no_slots"), show_alert=True)
        except Exception:
            pass
        return

    if not slots:
        try:
            await cb.message.edit_text(t(lang, "book.no_slots"))
        except Exception:
            await cb.message.answer(t(lang, "book.no_slots"))
        return

    # Build time buttons embedding session/location codes and date to survive FSM loss
    st_code = encode_stype(stype or "")
    loc_code = await encode_loc(loc)
    rows = [[(s.start.strftime("%H:%M"), f"time:{st_code}:{loc_code}:{int(s.start.timestamp())}:{date}")] for s in slots]
    await state.set_state(BookingStates.choosing_time)
    try:
        await cb.message.edit_text(t(lang, "book.choose_time"), reply_markup=ik_kbd(rows))
    except Exception:
        await cb.message.answer(t(lang, "book.choose_time"), reply_markup=ik_kbd(rows))


@router.callback_query(F.data.startswith("time:"))
async def choose_time(cb: CallbackQuery, state: FSMContext) -> None:
    lang = user_lang(cb)
    parts = (cb.data or "").split(":")
    if len(parts) < 5:
        await cb.answer(t(lang, "error.invalid_datetime"), show_alert=True)
        return
    st_code = parts[1]
    loc_code = parts[2]
    ts_str = parts[3]
    date_str = parts[4]
    # Decode codes (functions are tolerant and return defaults/None)
    session_type = decode_stype(st_code)
    location = await decode_loc(loc_code)
    await state.update_data(session_type=session_type, location=location, date=date_str)
    # Parse timestamp strictly; only catch parsing-related errors
    try:
        timestamp = float(ts_str)
        time_slot = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        await cb.answer(t(lang, "error.invalid_datetime"), show_alert=True)
        return

    data = await state.get_data()
    booking_data = BookingData(
        session_type=data.get("session_type"),
        location=data.get("location"),
        date=data.get("date"),
    )

    try:
        booking = await container.booking_flow().create_booking(
            cb.from_user.id,
            cb.from_user.full_name,
            booking_data,
            time_slot,
        )
        # Show payment/cancel options (payments unavailable yet)
        kbd = ik_kbd([[
            ("❌ " + t(lang, "book.cancel_button"), f"cancel:{booking['id']}") ,
            ("💳 " + t(lang, "book.pay_button"), f"pay:{booking['id']}")
        ]])
        await cb.message.edit_text(t(lang, "book.pay_unavailable"), reply_markup=kbd)
    except ValidationError:
        await cb.answer(t(lang, "book.no_slots"), show_alert=True)
        await state.clear()
        return

    await state.clear()


@router.callback_query(F.data.startswith("pay:"))
async def pay(cb: CallbackQuery) -> None:
    lang = user_lang(cb)
    booking_id = cb.data.split(":", 1)[1] if isinstance(cb.data, str) else ""
    repo = container.booking_repository()

    # Resolve booking and session type
    try:
        booking = repo.get_by_id_sync(booking_id) if booking_id else None
    except Exception as e:
        logger.error("Failed to fetch booking id=%s: %s", booking_id, e, exc_info=True)
        booking = None
    stype = (booking.get("session_type") if isinstance(booking, dict) else None) or ""
    suffix = _stype_suffix(stype)

    # Price from i18n; persist into booking if possible
    price_val = _get_price(lang, suffix)
    try:
        if booking_id:
            repo.patch_sync(booking_id, {"price": float(price_val)})
    except Exception as e:
        logger.warning("Failed to update price for booking id=%s: %s", booking_id, e)

    # Compose payment message
    text, url = _payment_message_text(lang, suffix, price_val)
    if text:
        try:
            await cb.message.answer(text, disable_web_page_preview=True)
        except Exception:
            await cb.message.answer(text)
        # Always acknowledge callback to remove the loading state
        with contextlib.suppress(Exception):
            await cb.answer()

        # Send a follow-up message with "Add to Google Calendar" button
        gcal_link = _build_gcal_link_from_booking(booking, lang) if booking else None
        if gcal_link:
            btn_label = "Add to Google Calendar"
            kbd = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=btn_label, url=gcal_link)]])
            followup_text = "📅"
            with contextlib.suppress(Exception):
                await cb.message.answer(followup_text, reply_markup=kbd)
    else:
        await cb.answer(t(lang, "book.pay_unavailable"), show_alert=True)


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_booking(cb: CallbackQuery) -> None:
    lang = user_lang(cb)
    booking_id = cb.data.split(":", 1)[1]
    try:
        container.calendar_service().cancel_booking(booking_id)
        await cb.message.edit_text(t(lang, "book.canceled"))
    except PermissionError:
        await cb.answer(t(lang, "book.cannot_cancel"), show_alert=True)
    await cb.answer()


@router.message(F.text.in_({"Мои записи", "My bookings", "📒 Мои записи", "📒 My bookings"}))
async def my_bookings(message: Message) -> None:
    lang = user_lang(message)
    uid = message.from_user.id if message and message.from_user else None
    if not uid:
        return

    # Collect session bookings (consultations)
    session_items = []
    try:
        session_items = container.calendar_service().list_user_bookings(uid) or []
    except Exception as e:
        logger.error("Failed to fetch user bookings for user_id=%s: %s", uid, e, exc_info=True)
        session_items = []

    # Collect cinema registrations
    event_repo = container.event_repository()
    reg_repo = container.event_registration_repository()
    cinema_items = []
    try:
        regs = await reg_repo.list_by_user(uid)
        for r in regs:
            ev_id = r.get("event_id")
            if not ev_id:
                continue
            try:
                ev = await event_repo.get_by_id(ev_id)
            except Exception as e:
                logger.warning("Failed to fetch event id=%s for user=%s: %s", ev_id, uid, e)
                ev = None
            if not ev:
                continue
            # Prepare a pseudo-booking dict to unify rendering
            when_dt = getattr(ev, "when", None)
            when_str = ""
            ts_sort = 0.0
            if when_dt:
                try:
                    when_utc = when_dt
                    when_str = when_utc.strftime("%Y-%m-%d %H:%M")
                    ts_sort = when_utc.timestamp()
                except (ValueError, TypeError, AttributeError) as e:
                    logger.debug("Failed to format event datetime for event_id=%s: %s", ev_id, e)
                    when_str = str(when_dt)
                    ts_sort = 0.0
            cinema_items.append({
                "_type": "cinema",
                "id": str(ev_id),
                "when_str": when_str,
                "ts": ts_sort,
                "title": getattr(ev, "title", ""),
                "place": getattr(ev, "place", ""),
            })
    except Exception as e:
        logger.error("Failed to fetch cinema registrations for user_id=%s: %s", uid, e, exc_info=True)
        cinema_items = []

    # Transform session bookings into unified items
    unified = []
    for b in (session_items or []):
        try:
            start_iso = b.get("start")
            when = ""
            ts = 0.0
            if isinstance(start_iso, str) and 'T' in start_iso:
                date_s = start_iso.split('T', 1)[0]
                time_s = start_iso.split('T', 1)[1][:5]
                when = f"{date_s} {time_s}"
                # Attempt to parse for sorting
                try:
                    ts = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).timestamp()
                except (ValueError, TypeError) as e:
                    logger.debug("Failed to parse booking start time for sorting: %s", e)
                    ts = 0.0
            location = b.get("location") or "Online"
            stype = b.get("session_type") or "Session"
            status = b.get("status") or ""
            unified.append({
                "_type": "session",
                "id": b.get("id"),
                "when_str": when,
                "ts": ts,
                "location": location,
                "stype": stype,
                "status": status,
            })
        except Exception as e:
            logger.warning("Failed to parse booking item: %s, error: %s", b, e)
            continue

    # Append cinema items
    unified.extend(cinema_items)

    if not unified:
        await message.answer(t(lang, "book.my_none"))
        return

    # Sort by time if available
    unified.sort(key=lambda x: x.get("ts") or 0)

    # Render all
    for it in unified:
        try:
            if it.get("_type") == "session":
                text = f"{t(lang, 'book.my_title')}\n• {it.get('when_str')} — {it.get('location')} — {it.get('stype')}\n{it.get('status')}"
                kbd = ik_kbd([[("❌ " + t(lang, "book.cancel_button"), f"cancel:{it.get('id')}")]])
            else:
                # Cinema event
                title = it.get("title") or ""
                place = it.get("place") or ""
                when_str = it.get("when_str") or ""
                text = f"🎬 {title}\n• {when_str} — {place}"
                kbd = ik_kbd([[('❌ ' + t(lang, 'book.cancel_button'), f"cancel_event:{it.get('id')}")]])
            await message.answer(text, reply_markup=kbd)
        except Exception:
            continue

