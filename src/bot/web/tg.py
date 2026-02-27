from __future__ import annotations

import logging
import secrets
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from aiogram import Bot, Dispatcher
from aiogram.types import Update
import pydantic

from ...config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tg", tags=["telegram"])

_TG_BOT: Bot | None = None
_TG_DP: Dispatcher | None = None
_WEBHOOK_PATH = "/webhook"
_WEBHOOK_HEADER = "X-Telegram-Bot-Api-Secret-Token"

def attach_bot(bot: Bot, dp: Dispatcher) -> None:
    global _TG_BOT, _TG_DP
    _TG_BOT, _TG_DP = bot, dp

@router.post(_WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    if not (_TG_BOT and _TG_DP and settings.use_webhook):
        return PlainTextResponse("webhook disabled", status_code=503)

    secret = settings.telegram_webhook_secret
    if not (isinstance(secret, str) and secret.strip()):
        raise HTTPException(status_code=503, detail="Webhook misconfigured")
        
    received = request.headers.get(_WEBHOOK_HEADER)
    if not (isinstance(received, str) and secrets.compare_digest(received, secret)):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        body = await request.body()
        update = Update.model_validate_json(body)
    except (ValueError, TypeError, pydantic.ValidationError) as e:
        logger.warning("Webhook: invalid update: %s", e)
        raise HTTPException(status_code=400, detail=f"Invalid update: {e}")
        
    await _TG_DP.feed_webhook_update(bot=_TG_BOT, update=update)
    return PlainTextResponse("ok")
