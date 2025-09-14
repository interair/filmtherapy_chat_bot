from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from .i18n.texts import t


def main_menu(lang: str) -> ReplyKeyboardMarkup:
    # Updated layout per request: rows -> [About], [Book, Online, My bookings], [Cinema, Recommend]
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=t(lang, "menu.about")),
            ],
            [
                KeyboardButton(text=t(lang, "menu.book")),
                KeyboardButton(text=t(lang, "menu.online")),
                KeyboardButton(text=t(lang, "menu.my_bookings")),
            ],
            [
                KeyboardButton(text=t(lang, "menu.cinema")),
                KeyboardButton(text=t(lang, "menu.recommend")),
            ],
        ],
        resize_keyboard=True,
    )
