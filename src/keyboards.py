from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from .i18n.texts import t


def main_menu(lang: str) -> ReplyKeyboardMarkup:
    # Updated layout per request: rows -> [About], [Book, Online, My bookings], [Cinema, Recommend]
    # Add emojis to each button label while keeping i18n keys unchanged
    about = f"ℹ️ {t(lang, 'menu.about')}"
    book = f"🗓️ {t(lang, 'menu.book')}"
    online = f"💻 {t(lang, 'menu.online')}"
    myb = f"📒 {t(lang, 'menu.my_bookings')}"
    cinema = f"🎬 {t(lang, 'menu.cinema')}"
    rec = f"🎥 {t(lang, 'menu.recommend')}"
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=about),
            ],
            [
                KeyboardButton(text=book),
                KeyboardButton(text=online),
                KeyboardButton(text=myb),
            ],
            [
                KeyboardButton(text=cinema),
                KeyboardButton(text=rec),
            ],
        ],
        resize_keyboard=True,
    )
