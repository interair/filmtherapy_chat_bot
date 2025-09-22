from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager


def _env_truthy(name: str, default: str = "0") -> bool:
    val = os.getenv(name, default)
    return str(val).lower() not in ("", "0", "false", "no", "off", "none")


PROFILE_STARTUP = _env_truthy("APP_PROFILE_STARTUP")


@contextmanager
def step(name: str, logger: logging.Logger | None = None, level: int = logging.INFO):
    """Context manager to log the duration of a code block if APP_PROFILE_STARTUP is enabled.

    Usage:
        with step("Create Bot", logger):
            bot = Bot(...)
    """
    if not PROFILE_STARTUP:
        yield
        return
    log = logger or logging.getLogger(__name__)
    t0 = time.monotonic()
    try:
        log.log(level, "Startup step begin: %s", name)
        yield
    finally:
        dt = (time.monotonic() - t0) * 1000.0
        log.log(level, "Startup step end: %s (%.1f ms)", name, dt)


def since_interpreter_start(label: str, logger: logging.Logger | None = None, level: int = logging.INFO) -> None:
    """Log how much time passed since Python interpreter start (sitecustomize.t0).

    Only logs if APP_PROFILE_STARTUP is enabled and sitecustomize.t0 is available.
    """
    if not PROFILE_STARTUP:
        return
    log = logger or logging.getLogger(__name__)
    try:
        import sitecustomize  # type: ignore
        t0 = getattr(sitecustomize, "t0", None)
    except Exception:  # pragma: no cover - optional
        t0 = None
    if t0 is None:
        return
    dt = (time.monotonic() - float(t0)) * 1000.0
    log.log(level, "Startup since interpreter: %s (%.1f ms)", label, dt)
