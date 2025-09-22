from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict
from ..services.storage import read_json


# Small in-memory cache for overrides to avoid disk I/O on each lookup
_OVERRIDES_CACHE: Dict[str, Dict[str, str]] = {"RU": {}, "EN": {}}
_OVERRIDES_MTIME: float | None = None

RU = {
    "menu.about": "О специалисте",
    "menu.book": "Записаться на консультацию",
    "menu.my_bookings": "Мои записи",
    "menu.sand": "Песочная терапия",
    "menu.online": "Онлайн-сессия",
    "menu.cinema": "Киноклуб",
    "menu.recommend": "Что посмотреть?",
    "start.welcome": "Здравствуйте! Я помогу записаться на консультацию и мероприятия. Выберите пункт меню:",

    "about.text": (
        "Меня зовут Галина. Психолог, опыт 7+ лет. Провожу очные и онлайн-консультации, "
        "песочную терапию. Контакты: @username, email@example.com"
    ),

    "book.choose_location": "Выберите локацию:",
    "book.choose_type": "Выберите тип сессии:",
    "book.choose_date": "Выберите дату:",
    "book.choose_time": "Выберите время:",
    "book.payment_link": "Для подтверждения перейдите по ссылке для оплаты:",
    "book.payment_url": "",
    "book.confirmed": "Бронирование подтверждено! Мы напомним за 24 часа.",
    "book.cancel_button": "Отменить встречу",
    "book.pay_button": "Оплатить",
    "book.pay_unavailable": "Оплата пока недоступна. Скоро добавим возможность оплатить!", 
    "book.cannot_cancel": "Нельзя отменить встречу менее чем за 24 часа. Возврат не осуществляется.",
    "book.canceled": "Ваша встреча отменена. Возврат оформлен согласно правилам.",
    "book.no_slots": "На выбранную дату нет доступных слотов.",
    "book.my_title": "Ваши записи:",
    "book.my_none": "У вас нет активных записей.",

    "sand.info": "Песочная терапия. Выберите дату и время:",
    "online.info": "Онлайн-сессия. Выберите дату и время:",

    "cinema.poster": "Ближайшие встречи киноклуба:",
    "cinema.register": "Записаться",
    "cinema.registered": "Вы зарегистрированы на встречу! Напомним заранее.",
    "cinema.canceled": "Вы отменили регистрацию на встречу киноклуба.",
    "cinema.already_registered": "Вы уже зарегистрированы на эту встречу.",

    "quiz.start": "Небольшой опрос: выберите настроение",
    "quiz.mood": "Выберите настроение:",
    "quiz.company": "С кем смотрите?",
    "quiz.result": "Подходит к просмотру:",

    "admin.help": "Команды: /admin_bookings, /admin_poster",
    "admin.no_access": "Нет доступа",

    "error.invalid_datetime": "Некорректная дата/время",

    "lang.choose": "Выберите язык / Choose language:",
    "lang.saved": "Язык сохранён. / Language saved.",
    "lang.ru": "Русский",
    "lang.en": "English",
    "free": "Бесплатно",
    "price.online": "90",
    "price.offline": "90",
    "price.sand": "90",
    "price.cinema": "90",
    "book.payment_link.online": "Для подтверждения онлайн-сессии оплатите по ссылке:",
    "book.payment_link.offline": "Для подтверждения очной консультации оплатите по ссылке:",
    "book.payment_link.sand": "Для подтверждения песочной терапии оплатите по ссылке:",
    "book.payment_link.cinema": "Для подтверждения участия оплатите по ссылке:",
}

EN = {
    "menu.about": "About",
    "menu.book": "Book a consultation",
    "menu.my_bookings": "My bookings",
    "menu.sand": "Sand therapy",
    "menu.online": "Online session",
    "menu.cinema": "Film club",
    "menu.recommend": "What to watch?",
    "start.welcome": "Hello! I can help you book sessions and events. Choose from the menu:",

    "about.text": (
        "My name is Galina. Psychologist with 7+ years of experience. In-person and online, sand therapy. "
        "Contacts: @username, email@example.com"
    ),

    "book.choose_location": "Choose location:",
    "book.choose_type": "Choose session type:",
    "book.choose_date": "Choose a date:",
    "book.choose_time": "Choose a time:",
    "book.payment_link": "To confirm, follow the payment link:",
    "book.payment_url": "",
    "book.confirmed": "Booking confirmed! We'll remind you 24h before.",
    "book.cancel_button": "Cancel meeting",
    "book.pay_button": "Pay",
    "book.pay_unavailable": "Payments are not available yet. Coming soon!",
    "book.cannot_cancel": "Cannot cancel less than 24 hours before start. No refund.",
    "book.canceled": "Your meeting was canceled. Refund per rules.",
    "book.no_slots": "No available slots for the selected date.",
    "book.my_title": "Your bookings:",
    "book.my_none": "You have no bookings.",

    "sand.info": "Sand therapy. Choose date and time:",
    "online.info": "Online session. Choose date and time:",

    "cinema.poster": "Upcoming film club events:",
    "cinema.register": "Register",
    "cinema.registered": "You are registered! We'll remind you.",
    "cinema.canceled": "Your registration was canceled.",
    "cinema.already_registered": "You are already registered for this event.",

    "quiz.start": "Mini quiz: choose your mood",
    "quiz.mood": "Pick your mood:",
    "quiz.company": "Who are you watching with?",
    "quiz.result": "Recommended:",

    "admin.help": "Commands: /admin_bookings, /admin_poster",
    "admin.no_access": "No access",

    "error.invalid_datetime": "Invalid date/time",
    "free": "Free",
    "price.online": "90",
    "price.offline": "90",
    "price.sand": "90",
    "price.cinema": "90",
    "book.payment_link.online": "To confirm the online session, pay via the link:",
    "book.payment_link.offline": "To confirm the in-person session, pay via the link:",
    "book.payment_link.sand": "To confirm the sand therapy session, pay via the link:",
    "book.payment_link.cinema": "To confirm your participation, pay via the link:",
}

# Path to overrides (JSON) stored alongside other data in src/data
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
TEXTS_OVERRIDES_PATH = DATA_DIR / "texts.json"


def _load_overrides() -> Dict[str, Dict[str, str]]:
    global _OVERRIDES_CACHE, _OVERRIDES_MTIME
    try:
        if not TEXTS_OVERRIDES_PATH.exists():
            _OVERRIDES_CACHE = {"RU": {}, "EN": {}}
            _OVERRIDES_MTIME = None
            return _OVERRIDES_CACHE
        mtime = os.path.getmtime(TEXTS_OVERRIDES_PATH)
        if _OVERRIDES_MTIME == mtime:
            return _OVERRIDES_CACHE
        data = read_json(TEXTS_OVERRIDES_PATH, default={})
        if not isinstance(data, dict):
            _OVERRIDES_CACHE = {"RU": {}, "EN": {}}
        else:
            # Sanitize structure
            ru = data.get("RU") or {}
            en = data.get("EN") or {}
            if not isinstance(ru, dict) or not isinstance(en, dict):
                _OVERRIDES_CACHE = {"RU": {}, "EN": {}}
            else:
                # Cast values to str
                ru = {str(k): str(v) for k, v in ru.items()}
                en = {str(k): str(v) for k, v in en.items()}
                _OVERRIDES_CACHE = {"RU": ru, "EN": en}
        _OVERRIDES_MTIME = mtime
        return _OVERRIDES_CACHE
    except Exception:
        return _OVERRIDES_CACHE


def t(lang: str, key: str) -> str:
    is_ru = (lang or "ru").startswith("ru")
    base = RU if is_ru else EN
    overrides = _load_overrides()
    val = overrides.get("RU" if is_ru else "EN", {}).get(key)
    if val is not None and val != "":
        return val
    return base.get(key, key)
