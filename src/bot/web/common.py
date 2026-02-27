from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import Request
from starlette.templating import Jinja2Templates

from ...config import settings

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))

class QueryFlags:
    """Common query flags like saved=1, deleted=1, etc., parsed uniformly."""
    def __init__(self, saved: int = 0, deleted: int = 0, added: int = 0, updated: int = 0, created: int = 0):
        self.saved = (saved == 1)
        self.deleted = (deleted == 1)
        self.added = (added == 1)
        self.updated = (updated == 1)
        self.created = (created == 1)

def _get_commit_hash() -> str:
    commit = (
        os.getenv("GIT_COMMIT")
        or os.getenv("COMMIT_SHA")
        or os.getenv("SOURCE_COMMIT")
        or os.getenv("COMMIT")
    )
    if not commit:
        for p in (ROOT_DIR / "commit.txt", Path("/app/commit.txt")):
            try:
                if p.exists():
                    commit = p.read_text(encoding="utf-8").strip() or None
                    if commit:
                        break
            except OSError:
                logger.debug("Failed to read commit from %s", p, exc_info=True)
    return commit or "unknown"

_COMMIT_HASH = _get_commit_hash()

def render(request: Request, template: str, context: dict[str, Any] | None = None, flags: QueryFlags | None = None):
    """Unified render helper that injects common context and bot status."""
    from ..webapp import is_bot_running
    
    ctx = {
        "request": request,
        "bot_running": is_bot_running(),
        "commit": _COMMIT_HASH,
        "debug": settings.debug,
    }
    if context:
        ctx.update(context)
    if flags:
        ctx["flags"] = flags
    return templates.TemplateResponse(template, ctx)

def _is_multiline(key: str, value: str) -> bool:
    return ("\n" in value) or (len(value) > 120) or key.endswith(".text")

templates.env.globals["is_multiline"] = _is_multiline
