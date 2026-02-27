from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from aiogram import Bot, Dispatcher
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..config import settings
from .web import admin, events, bookings, schedule, quiz, i18n, about, locations, tg

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[1]

# Bot runtime indicator (updated from main.py)
_BOT_RUNNING = False

def mark_bot_running(is_running: bool) -> None:
    global _BOT_RUNNING
    _BOT_RUNNING = bool(is_running)

def is_bot_running() -> bool:
    return bool(_BOT_RUNNING)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic: ensure webhook is set if configured
    bot = tg._TG_BOT
    if bot and settings.use_webhook and settings.base_url:
        # Use full path for webhook as defined in tg.router
        url = f"{settings.base_url.rstrip('/')}/tg/webhook"
        secret = settings.telegram_webhook_secret
        try:
            await bot.set_webhook(url=url, secret_token=secret)
            logger.info("Webhook set: %s", url)
        except Exception as e:
            logger.error("Failed to set webhook on startup: %s", e)
    
    yield
    
    # Shutdown logic
    # No-op for now

app = FastAPI(lifespan=lifespan, title="Gantich Bot Admin")
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "data")), name="static")

# Include Routers
app.include_router(tg.router)
app.include_router(admin.router)
app.include_router(events.router)
app.include_router(bookings.router)
app.include_router(schedule.router)
app.include_router(quiz.router)
app.include_router(i18n.router)
app.include_router(about.router)
app.include_router(locations.router)

def attach_bot(bot: Bot, dp: Dispatcher) -> None:
    tg.attach_bot(bot, dp)

async def start_web(bot: Bot | None = None, dp: Dispatcher | None = None) -> None:
    if bot and dp:
        attach_bot(bot, dp)
    
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=settings.web_port,
        log_level="info",
        access_log=True,
    )
    server = uvicorn.Server(config)
    await server.serve()
