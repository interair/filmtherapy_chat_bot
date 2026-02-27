from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .bot.routers import booking, cinema, quiz, admin
from .bot.routers import start as start_router
from .bot.webapp import start_web, mark_bot_running
from .config import settings

# Configure logging to stdout only (cloud-native friendly)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def build_dispatcher() -> Dispatcher:
    # Ensure FSM storage is explicitly set for reliability
    from aiogram.fsm.storage.memory import MemoryStorage
    dp = Dispatcher(storage=MemoryStorage())
    # include routers
    dp.include_router(start_router.router)
    dp.include_router(booking.router)
    dp.include_router(cinema.router)
    dp.include_router(quiz.router)
    dp.include_router(admin.router)
    return dp


async def main() -> None:
    bot = Bot(token=settings.telegram_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher()

    # Decide whether to start web server (admin UI and/or webhook endpoint)
    web_needed = bool(settings.use_webhook) or bool(settings.web_username and settings.web_password)

    # Start web server; attach bot/dispatcher if running in webhook mode
    web_task = None
    if web_needed:
        # Pass bot and dp so webhook endpoint can process updates
        web_task = asyncio.create_task(start_web(bot, dp))
        logger.info("Starting web server on port %s (webhook=%s, admin_ui=%s)", settings.web_port, settings.use_webhook, bool(settings.web_username and settings.web_password))
    else:
        logger.info("Web server disabled (set USE_WEBHOOK=true or provide WEB_USERNAME/WEB_PASSWORD to enable)")

    try:
        mark_bot_running(True)
        if settings.use_webhook and settings.base_url:
            # Webhook mode: web server handles updates; keep main task alive
            logger.info("Running in webhook mode with base URL: %s", settings.base_url)
            await asyncio.Event().wait()
        else:
            # Polling mode: ensure any existing webhook is removed to avoid conflicts
            try:
                await bot.delete_webhook(drop_pending_updates=True)
                logger.info("Ensured webhook is removed before polling")
            except Exception as e:
                logger.warning("Failed to delete webhook before polling: %s", e)
            await dp.start_polling(bot)
    finally:
        mark_bot_running(False)
        if web_task:
            web_task.cancel()
            with contextlib.suppress(Exception):
                await web_task


if __name__ == "__main__":
    # Use a fork-safe start method for any multiprocessing needs.
    # Forking with asyncio/aiogram can lead to subtle bugs (duplicated event loops, open sockets).
    # 'spawn' ensures a clean interpreter state in child processes.
    try:
        import multiprocessing as _mp  # local import to avoid import-time side effects
        # If not already set to 'spawn', enforce it before any child processes are created.
        if getattr(_mp, "get_start_method", None):
            cur = _mp.get_start_method(allow_none=True)
            if cur != "spawn":
                _mp.set_start_method("spawn", force=True)
    except Exception as _e:  # best-effort only
        logger.debug("Could not set multiprocessing start method to 'spawn': %s", _e)

    asyncio.run(main())
