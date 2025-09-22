from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
import uvicorn
import logging
import pydantic

from aiogram import Bot, Dispatcher
from aiogram.types import Update

from ..config import settings
from ..i18n.texts import RU, EN
from ..services.repositories import EventRepository, LocationRepository, QuizRepository, AboutRepository, ScheduleRepository, SessionLocationsRepository
from ..container import container

from .dependencies import (
    verify_web_auth,
    get_event_service,
    get_location_service,
    get_quiz_service,
    get_event_repository,
    get_about_repository,
    get_schedule_repository,
    get_metrics_service,
    get_event_registration_repository,
    get_session_locations_repository,
)
from ..services.event_service import EventService
from ..services.models import SessionType
from ..exceptions import BotException
from ..services.storage import read_json, write_json

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[1]
TEXTS_PATH = (ROOT_DIR / "data" / "texts.json")

app = FastAPI()
app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "data")), name="static")
templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))

# Telegram webhook integration
_TG_BOT: Optional[Bot] = None
_TG_DP: Optional[Dispatcher] = None
_WEBHOOK_PATH = "/tg/webhook"

# Bot runtime indicator (updated from main.py)
_BOT_RUNNING = False

def mark_bot_running(is_running: bool) -> None:
    global _BOT_RUNNING
    _BOT_RUNNING = bool(is_running)

def is_bot_running() -> bool:
    return bool(_BOT_RUNNING)


# Attach aiogram bot/dispatcher for webhook mode

def attach_bot(bot: Bot, dp: Dispatcher) -> None:
    global _TG_BOT, _TG_DP
    _TG_BOT, _TG_DP = bot, dp


# Telegram webhook endpoint (no auth)
@app.post(_WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    if not (_TG_BOT and _TG_DP and settings.use_webhook):
        client = getattr(request, "client", None)
        ip = getattr(client, "host", None) if client else None
        logger.warning("Webhook called while disabled (ip=%s)", ip)
        return PlainTextResponse("webhook disabled", status_code=503)
    try:
        body = await request.body()
        logger.info("Webhook: received update bytes=%d", len(body) if body is not None else 0)
        update = Update.model_validate_json(body)
    except (ValueError, TypeError, pydantic.ValidationError) as e:
        logger.warning("Webhook: invalid update: %s", e)
        raise HTTPException(status_code=400, detail=f"Invalid update: {e}")
    await _TG_DP.feed_webhook_update(bot=_TG_BOT, update=update)
    return PlainTextResponse("ok")


# Set/delete webhook on app lifecycle
@app.on_event("startup")
async def _on_startup():
    if _TG_BOT and settings.use_webhook and settings.base_url:
        url = settings.base_url.rstrip("/") + _WEBHOOK_PATH
        await _TG_BOT.set_webhook(url=url)
        logger.info("Webhook set: %s", url)


@app.on_event("shutdown")
async def _on_shutdown():
    # Do not delete webhook on shutdown; keep it as-is to avoid flapping between deployments.
    # Intentionally left as a no-op.
    return


def html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _read_texts_overrides() -> dict:
    """Read texts overrides using shared storage helpers to avoid duplication."""
    try:
        data = read_json(TEXTS_PATH, default={})
        if not isinstance(data, dict):
            return {"RU": {}, "EN": {}}
        return {"RU": dict(data.get("RU", {})), "EN": dict(data.get("EN", {}))}
    except Exception:
        logger.debug("Failed to read texts overrides from %s", TEXTS_PATH, exc_info=True)
        return {"RU": {}, "EN": {}}


def _write_texts_overrides(data: dict) -> None:
    """Write texts overrides using shared storage helpers to avoid duplication."""
    TEXTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(TEXTS_PATH, data)


def _all_i18n_keys() -> list[str]:
    return sorted(set(list(RU.keys()) + list(EN.keys())))


def _is_multiline(key: str, value: str) -> bool:
    return ("\n" in value) or (len(value) > 120) or key.endswith(".text")

# Make helper available inside Jinja templates
templates.env.globals["is_multiline"] = _is_multiline


@app.get("/", response_class=HTMLResponse)
async def web_index(request: Request, metrics = Depends(get_metrics_service), _: None = Depends(verify_web_auth)):
    saved = request.query_params.get("saved") == "1"
    deleted = request.query_params.get("deleted") == "1"
    added = request.query_params.get("added") == "1"
    updated = request.query_params.get("updated") == "1"
    time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    overview = metrics.today_overview()
    top_features = metrics.feature_usage(days=7, top_n=3)
    # Count bookings created today (UTC) for attention banner
    new_bookings_today = 0
    try:
        raw_bookings = container.calendar_service().list_all_bookings()
        if raw_bookings:
            today_utc = datetime.utcnow().date()
            for b in raw_bookings:
                created = b.get('created_at') or b.get('created')
                if isinstance(created, str) and created:
                    try:
                        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        d_utc = (dt.astimezone(timezone.utc).date() if dt.tzinfo else dt.date())
                        if d_utc == today_utc:
                            new_bookings_today += 1
                    except Exception:
                        logger.debug("Ignoring invalid booking created timestamp: %r", created, exc_info=True)
                        continue
    except Exception:
        logger.exception("Failed to compute new bookings today")
        new_bookings_today = 0
    return templates.TemplateResponse("index.html", {
        "request": request,
        "saved": saved,
        "deleted": deleted,
        "added": added,
        "updated": updated,
        "time_str": time_str,
        "metrics_overview": overview,
        "top_features": top_features,
        "new_bookings_today": new_bookings_today,
        "bot_running": is_bot_running(),
    })


@app.get("/system", response_class=HTMLResponse)
async def web_system(request: Request, _: None = Depends(verify_web_auth)):
    time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Determine bot mode
    bot_mode = "webhook" if settings.use_webhook and settings.base_url else "polling"

    # Build configuration dict using a whitelist of non-sensitive fields
    cfg = settings.model_dump()
    allowed_keys = {"admins", "base_url", "default_lang", "use_webhook", "web_port"}
    safe_cfg = {}
    for k in sorted(allowed_keys):
        if k in cfg:
            safe_cfg[k] = cfg.get(k)

    # Add a few useful env/runtime values
    extra_env_keys = [
        "GOOGLE_CLOUD_PROJECT", "K_SERVICE", "K_REVISION", "K_CONFIGURATION",
    ]
    runtime_env = {k: os.getenv(k) for k in extra_env_keys if os.getenv(k) is not None}

    # Resolve commit/version information
    commit = (
        os.getenv("GIT_COMMIT")
        or os.getenv("COMMIT_SHA")
        or os.getenv("SOURCE_COMMIT")
        or os.getenv("COMMIT")
    )
    if not commit:
        # Try to read from a file if provided during build/deploy
        for p in (ROOT_DIR / "commit.txt", Path("/app/commit.txt")):
            try:
                if p.exists():
                    commit = p.read_text(encoding="utf-8").strip() or None
                    break
            except OSError:
                logger.debug("Failed to read commit from %s", p, exc_info=True)
    commit = commit or "unknown"

    context = {
        "request": request,
        "time_str": time_str,
        "bot_status": ("Running" if is_bot_running() else "Stopped"),
        "bot_mode": bot_mode,
        "web_editor": ("Enabled" if settings.is_web_enabled else "Disabled"),
        "config": safe_cfg,
        "runtime_env": runtime_env,
        "commit": commit,
    }
    return templates.TemplateResponse("system.html", context)


@app.get("/events", response_class=HTMLResponse)
async def web_events(
    request: Request,
    event_service: EventService = Depends(get_event_service),
    reg_repo = Depends(get_event_registration_repository),
    _: None = Depends(verify_web_auth),
):
    events = await event_service.list_upcoming_events()
    attendees: dict[str, list[dict]] = {}
    try:
        for ev in events:
            try:
                regs = await reg_repo.get_by_event(ev.id)
                attendees[ev.id] = regs if regs else []
            except BotException as e:
                logging.getLogger(__name__).error(f"Failed to get registrations for event {ev.id}: {e}")
                attendees[ev.id] = []
    except BotException as e:
        logging.getLogger(__name__).error(f"Failed to load event attendees: {e}")
        attendees = {}
    
    return templates.TemplateResponse("events.html", {"request": request, "poster": events, "attendees": attendees})


@app.get("/events/add", response_class=HTMLResponse)
async def web_events_add(
    request: Request,
    loc_repo: LocationRepository = Depends(get_location_service),
    _: None = Depends(verify_web_auth),
):
    loc_models = await loc_repo.get_all()
    locs = [l.name for l in loc_models]
    return templates.TemplateResponse("events_add.html", {"request": request, "locs": locs})


@app.get("/events/edit/{id}", response_class=HTMLResponse)
async def web_events_edit(
    id: str,
    request: Request,
    event_repo: EventRepository = Depends(get_event_repository),
    loc_repo: LocationRepository = Depends(get_location_service),
    _: None = Depends(verify_web_auth),
):
    event = await event_repo.get_by_id(id)
    if not event:
        return HTMLResponse(content="Event not found", status_code=404)
    # Format datetime for input value (HTML datetime-local does not support timezone)
    try:
        when_value = event.when.replace(microsecond=0, tzinfo=None).isoformat(timespec="seconds")
    except (AttributeError, ValueError, TypeError):
        when_value = event.when.replace(microsecond=0).isoformat()
    loc_models = await loc_repo.get_all()
    locs = [l.name for l in loc_models]
    return templates.TemplateResponse("events_edit.html", {"request": request, "event": event, "locs": locs, "when_value": when_value})


@app.post("/events/save")
async def web_events_save(
    request: Request,
    event_repo: EventRepository = Depends(get_event_repository),
    _: None = Depends(verify_web_auth),
):
    data = await request.form()

    event_id = data.get('id') or f"event-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    when_value = str(data['when'])
    if 'T' in when_value and len(when_value) == 16:
        when_value += ":00"

    price_val: Optional[float] = None
    if data.get('price') not in (None, ""):
        try:
            price_val = float(data.get('price'))
        except (ValueError, TypeError):
            price_val = None

    # Handle optional photo upload
    photo_filename: Optional[str] = None
    file_field = data.get("photo")
    try:
        if file_field and getattr(file_field, 'filename', ''):
            # Read bytes (UploadFile has async read)
            content = await file_field.read() if hasattr(file_field, 'read') else bytes(file_field)  # type: ignore
            # Basic size limit: 10 MB
            if len(content) <= 10 * 1024 * 1024:
                ext = os.path.splitext(getattr(file_field, 'filename', ''))[1].lower()
                if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                    ext = ".jpg"
                safe_name = f"{event_id}{ext}"
                dst = ROOT_DIR / "data" / safe_name
                dst.parent.mkdir(parents=True, exist_ok=True)
                with open(dst, "wb") as out:
                    out.write(content)
                photo_filename = safe_name
    except (OSError, ValueError, TypeError):
        # Ignore upload errors and continue without photo
        photo_filename = None

    from ..services.models import Event

    # Preserve existing photo if not replaced
    existing = await event_repo.get_by_id(str(event_id))
    logger.info("Web: events/save id=%s existing=%s", str(event_id), bool(existing))
    if existing and getattr(existing, "photo", None) and not photo_filename:
        photo_filename = existing.photo

    new_event = Event(
        id=str(event_id),
        title=str(data['title']),
        when=str(when_value),  # Pydantic will parse ISO string
        place=str(data['place']),
        price=price_val,
        description=str(data.get('description', '') or None),
        photo=photo_filename,
    )

    # Create or update via repository
    if existing:
        await event_repo.update(new_event)
        action = "updated"
    else:
        await event_repo.create(new_event)
        action = "added"

    logger.info("Web: event %s %s", str(event_id), action)
    return RedirectResponse(url=f"/events?{action}=1", status_code=302)


@app.get("/events/delete/{id}")
async def web_events_delete(
    id: str,
    event_repo: EventRepository = Depends(get_event_repository),
    _: None = Depends(verify_web_auth),
):
    logger.info("Web: events/delete id=%s", id)
    await event_repo.delete(id)
    return RedirectResponse(url="/events?deleted=1", status_code=302)

@app.get("/quiz", response_class=HTMLResponse)
async def web_quiz(
    request: Request,
    quiz_repo: QuizRepository = Depends(get_quiz_service),
    _: None = Depends(verify_web_auth),
):
    cfg = await quiz_repo.get_config()
    moods = cfg.get("moods", [])
    companies = cfg.get("companies", [])
    recs = cfg.get("recs", {})
    moods_text = "\n".join(f"{m.get('title','')}|{m.get('code','')}" for m in moods)
    companies_text = "\n".join(f"{c.get('title','')}|{c.get('code','')}" for c in companies)
    return templates.TemplateResponse("quiz.html", {
        "request": request,
        "moods": moods,
        "companies": companies,
        "recs": recs,
        "moods_text": moods_text,
        "companies_text": companies_text,
    })


@app.post("/quiz/save")
async def web_quiz_save(
    request: Request,
    quiz_repo: QuizRepository = Depends(get_quiz_service),
    _: None = Depends(verify_web_auth),
):
    data = await request.form()
    # Parse moods/companies using shared helper
    moods_in = parse_title_code_lines(str(data.get("moods", "")))
    companies_in = parse_title_code_lines(str(data.get("companies", "")))

    # Parse recs
    recs_in = {}
    for name, value in data.items():
        if isinstance(name, str) and name.startswith("rec:"):
            key = name[4:]  # mood|company
            films = [s.strip() for s in str(value).splitlines() if s.strip()]
            recs_in[key] = films

    logger.info("Web: quiz/save moods=%d companies=%d recs=%d", len(moods_in), len(companies_in), len(recs_in))
    await quiz_repo.save_config({"moods": moods_in, "companies": companies_in, "recs": recs_in})
    return RedirectResponse(url="/quiz", status_code=302)


@app.get("/bookings", response_class=HTMLResponse)
async def web_bookings(request: Request, _: None = Depends(verify_web_auth)):
    deleted = request.query_params.get("deleted") == "1"
    raw = container.calendar_service().list_all_bookings()
    items = []
    for booking in raw:
        status = booking.get('status', 'Unknown')
        status_color = "green" if status == 'confirmed' else "orange"
        user_name = booking.get('name') or ''
        try:
            user_name_safe = str(user_name) if user_name else 'Unknown'
        except (ValueError, TypeError):
            user_name_safe = 'Unknown'
        start_iso = booking.get('start')
        date_str = 'Unknown'
        time_str = 'Unknown'
        if isinstance(start_iso, str) and 'T' in start_iso:
            dt = start_iso.split('T', 1)[0]
            tm = start_iso.split('T', 1)[1][:5]
            date_str = dt
            time_str = tm
        items.append({
            "id": booking.get('id', ''),
            "location": booking.get('location', 'Unknown'),
            "session_type": booking.get('session_type', 'Unknown'),
            "user_name": user_name_safe,
            "user_id": booking.get('user_id', 'Unknown'),
            "status": status,
            "status_color": status_color,
            "date_str": date_str,
            "time_str": time_str,
            "created_at": booking.get('created_at', 'Unknown'),
        })
    return templates.TemplateResponse("bookings.html", {"request": request, "items": items, "deleted": deleted})


@app.get("/schedule", response_class=HTMLResponse)
async def web_schedule(
    request: Request,
    sched_repo: ScheduleRepository = Depends(get_schedule_repository),
    loc_repo: LocationRepository = Depends(get_location_service),
    _: None = Depends(verify_web_auth),
):
    saved = request.query_params.get("saved") == "1"
    cfg = await sched_repo.get()
    rules = cfg.get("rules", []) if isinstance(cfg, dict) else []
    # Load available locations for dropdown
    try:
        loc_items = await loc_repo.get_all()
        locations = [l.name for l in loc_items]
    except BotException:
        locations = []
    # Define known session types for dropdown (explicit: Онлайн / Офлайн)
    session_types = ["Онлайн", "Офлайн"]
    return templates.TemplateResponse("schedule.html", {
        "request": request,
        "saved": saved,
        "rules": rules,
        "locations": locations,
        "session_types": session_types,
    })


@app.post("/schedule/save")
async def web_schedule_save(
    request: Request,
    sched_repo: ScheduleRepository = Depends(get_schedule_repository),
    _: None = Depends(verify_web_auth),
):
    data = await request.form()
    # Read multiple values per field (FormData supports getlist)
    def _list(key: str) -> list:
        try:
            return [v for v in data.getlist(key) if v is not None]
        except AttributeError:
            v = data.get(key)
            return [v] if v is not None else []

    weekdays = _list("weekday")
    starts = _list("start")
    ends = _list("end")
    durations = _list("duration")
    intervals = _list("interval")
    locations = _list("location")
    session_types = _list("session_type")

    n = max(len(weekdays), len(starts), len(ends), len(durations), len(intervals), len(locations), len(session_types))
    rules = []
    for i in range(n):
        try:
            wd = int((weekdays[i] if i < len(weekdays) else -1))
        except (ValueError, TypeError):
            wd = -1
        start = str(starts[i]) if i < len(starts) else ""
        end = str(ends[i]) if i < len(ends) else ""
        try:
            duration = int(durations[i]) if i < len(durations) and str(durations[i]).strip() else 50
        except (ValueError, TypeError):
            duration = 50
        try:
            interval = int(intervals[i]) if i < len(intervals) and str(intervals[i]).strip() else duration
        except (ValueError, TypeError):
            interval = duration
        location = str(locations[i]) if i < len(locations) else ""
        sess = str(session_types[i]) if i < len(session_types) else ""
        if 0 <= wd <= 6 and start and end:
            rules.append({
                "weekday": wd,
                "start": start,
                "end": end,
                "duration": duration,
                "interval": interval,
                "location": location,
                "session_type": sess,
            })

    logger.info("Web: schedule/save rules=%d", len(rules))
    await sched_repo.save({"rules": rules})
    return RedirectResponse(url="/schedule?saved=1", status_code=302)


@app.get("/i18n", response_class=HTMLResponse)
async def web_i18n(request: Request, _: None = Depends(verify_web_auth)):
    saved_flag = request.query_params.get("saved")
    overrides = _read_texts_overrides()
    keys = _all_i18n_keys()
    ru_vals: dict[str, str] = {}
    en_vals: dict[str, str] = {}
    for key in keys:
        ru_vals[key] = overrides.get("RU", {}).get(key, RU.get(key, ""))
        en_vals[key] = overrides.get("EN", {}).get(key, EN.get(key, ""))
    return templates.TemplateResponse("i18n.html", {
        "request": request,
        "keys": keys,
        "ru": ru_vals,
        "en": en_vals,
        "saved": bool(saved_flag),
    })


@app.post("/i18n/save")
async def web_i18n_save(request: Request, _: None = Depends(verify_web_auth)):
    data = await request.form()
    ru_over: dict[str, str] = {}
    en_over: dict[str, str] = {}
    for name, value in data.items():
        if isinstance(name, str) and name.startswith("ru:"):
            k = name[3:]
            v = str(value)
            if v != RU.get(k, ""):
                ru_over[k] = v
        elif isinstance(name, str) and name.startswith("en:"):
            k = name[3:]
            v = str(value)
            if v != EN.get(k, ""):
                en_over[k] = v
    _write_texts_overrides({"RU": ru_over, "EN": en_over})
    logger.info("Web: i18n/save RU=%d EN=%d", len(ru_over), len(en_over))
    return RedirectResponse(url="/i18n?saved=1", status_code=302)


async def start_web(bot: Bot | None = None, dp: Dispatcher | None = None) -> None:
    # Attach bot/dispatcher if provided (for webhook mode)
    if bot is not None and dp is not None:
        attach_bot(bot, dp)
    config = uvicorn.Config(app=app, host="0.0.0.0", port=settings.web_port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()



@app.get("/about", response_class=HTMLResponse)
async def web_about(
    request: Request,
    about_repo: AboutRepository = Depends(get_about_repository),
    _: None = Depends(verify_web_auth),
):
    saved = request.query_params.get("saved") == "1"
    cfg = await about_repo.get()
    fn = cfg.get("photo") if isinstance(cfg, dict) else None
    photo = fn if isinstance(fn, str) and fn else ""
    return templates.TemplateResponse("about.html", {"request": request, "saved": saved, "photo": photo})


@app.post("/about/save")
async def web_about_save(
    request: Request,
    about_repo: AboutRepository = Depends(get_about_repository),
    _: None = Depends(verify_web_auth),
):
    data = await request.form()
    file_field = data.get("photo")
    if not file_field:
        return RedirectResponse(url="/about", status_code=302)
    try:
        filename = getattr(file_field, 'filename', '') or 'about_photo'
        # Read bytes (UploadFile has async read)
        if hasattr(file_field, 'read'):
            content = await file_field.read()  # type: ignore
        else:
            content = bytes(file_field)
        # Basic size limit: 10 MB
        if len(content) > 10 * 1024 * 1024:
            return PlainTextResponse(content="File too large", status_code=400)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        safe_name = f"about_photo{ext}"
        dst = ROOT_DIR / "data" / safe_name
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(dst, "wb") as out:
            out.write(content)
        await about_repo.set_photo(safe_name)
        logger.info("Web: about/save file=%s bytes=%d", safe_name, len(content) if isinstance(content, (bytes, bytearray)) else -1)
        return RedirectResponse(url="/about?saved=1", status_code=302)
    except Exception as e:
        logger.exception("Web: about/save failed")
        return PlainTextResponse(content=f"Upload failed: {html_escape(str(e))}", status_code=500)


# Locations management
@app.get("/locations", response_class=HTMLResponse)
async def web_locations(
    request: Request,
    loc_repo: LocationRepository = Depends(get_location_service),
    _: None = Depends(verify_web_auth),
):
    saved = request.query_params.get("saved") == "1"
    deleted = request.query_params.get("deleted") == "1"
    loc_models = await loc_repo.get_all()
    locs = [l.name for l in loc_models]
    items = []
    for s in locs:
        try:
            enc = base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii").rstrip("=")
        except Exception:
            logger.debug("Failed to base64-encode location name: %r", s, exc_info=True)
            enc = ""
        items.append({"name": s, "enc": enc})
    return templates.TemplateResponse("locations.html", {
        "request": request,
        "items": items,
        "saved": saved,
        "deleted": deleted,
    })


@app.post("/locations/add")
async def web_locations_add(
    request: Request,
    loc_repo: LocationRepository = Depends(get_location_service),
    _: None = Depends(verify_web_auth),
):
    data = await request.form()
    name = str(data.get("name", "")).strip()
    if name:
        logger.info("Web: locations/add name=%s", name)
        from ..services.models import Location
        try:
            await loc_repo.create(Location(name=name))
        except ValueError:
            logger.debug("Failed to create location (invalid value): %r", name, exc_info=True)
    return RedirectResponse(url="/locations?saved=1", status_code=302)


@app.get("/locations/delete/{val}")
async def web_locations_delete(
    val: str,
    loc_repo: LocationRepository = Depends(get_location_service),
    _: None = Depends(verify_web_auth),
):
    enc = val
    try:
        pad = "=" * (-len(enc) % 4)
        name = base64.urlsafe_b64decode((enc + pad).encode("ascii")).decode("utf-8")
    except Exception:
        logger.debug("Failed to base64-decode location for delete: %r", enc, exc_info=True)
        name = ""
    if name:
        logger.info("Web: locations/delete name=%s", name)
        await loc_repo.delete(name)
    return RedirectResponse(url="/locations?deleted=1", status_code=302)


# Per-type locations management
@app.get("/locations/types", response_class=HTMLResponse)
async def web_locations_by_type(
    request: Request,
    repo: SessionLocationsRepository = Depends(get_session_locations_repository),
    loc_repo: LocationRepository = Depends(get_location_service),
    _: None = Depends(verify_web_auth),
):
    saved = request.query_params.get("saved") == "1"
    deleted = request.query_params.get("deleted") == "1"
    m = await repo.get_map()
    # Filter out any 'online' keys from the map (both ru/en)
    def _is_online_key(s: str) -> bool:
        s_low = (s or "").strip().lower()
        return ("online" in s_low) or ("онлайн" in s_low)
    m = {k: v for k, v in m.items() if not _is_online_key(k)}
    # Also list all known locations to help adding
    try:
        loc_models = await loc_repo.get_all()
        all_locations = [l.name for l in loc_models]
    except Exception:
        logger.debug("Failed to load all locations", exc_info=True)
        all_locations = []
    # Prepare view model with encoded values for delete links
    items = []
    for key in sorted(m.keys()):
        locs = []
        for s in m[key]:
            try:
                enc = base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii").rstrip("=")
            except Exception:
                logger.debug("Failed to base64-encode location in type map: %r", s, exc_info=True)
                enc = ""
            locs.append({"name": s, "enc": enc})
        try:
            key_enc = base64.urlsafe_b64encode(key.encode("utf-8")).decode("ascii").rstrip("=")
        except Exception:
            logger.debug("Failed to base64-encode session type key: %r", key, exc_info=True)
            key_enc = ""
        items.append({"type": key, "type_enc": key_enc, "locs": locs})
    # Build session types list excluding ONLINE
    session_types = [it.value for it in SessionType if getattr(SessionType, 'ONLINE', None) is None or it != SessionType.ONLINE]
    return templates.TemplateResponse("locations_by_type.html", {
        "request": request,
        "items": items,
        "all_locations": all_locations,
        "session_types": session_types,
        "saved": saved,
        "deleted": deleted,
    })


@app.post("/locations/types/add")
async def web_locations_by_type_add(
    request: Request,
    repo: SessionLocationsRepository = Depends(get_session_locations_repository),
    _: None = Depends(verify_web_auth),
):
    data = await request.form()
    type_key = str(data.get("type") or data.get("type_key") or "").strip()
    name = str(data.get("name", "")).strip()
    # Disallow adding mappings for online type (ru/en)
    low = type_key.lower()
    if ("online" in low) or ("онлайн" in low):
        return RedirectResponse(url="/locations/types?saved=1", status_code=302)
    if type_key and name:
        logger.info("Web: locations/types/add type=%s name=%s", type_key, name)
        try:
            await repo.add(type_key, name)
        except Exception:
            logger.debug("Failed to add mapping for type=%r name=%r", type_key, name, exc_info=True)
    return RedirectResponse(url="/locations/types?saved=1", status_code=302)


@app.get("/locations/types/delete/{type_enc}/{val}")
async def web_locations_by_type_del(
    type_enc: str,
    val: str,
    repo: SessionLocationsRepository = Depends(get_session_locations_repository),
    _: None = Depends(verify_web_auth),
):
    def _dec(s: str) -> str:
        try:
            pad = "=" * (-len(s) % 4)
            return base64.urlsafe_b64decode((s + pad).encode("ascii")).decode("utf-8")
        except Exception:
            return ""
    t = _dec(type_enc)
    name = _dec(val)
    if t and name:
        logger.info("Web: locations/types/delete type=%s name=%s", t, name)
        try:
            await repo.remove(t, name)
        except Exception:
            logger.debug("Failed to remove mapping for type=%r name=%r", t, name, exc_info=True)
    return RedirectResponse(url="/locations/types?deleted=1", status_code=302)



@app.post("/events")
async def create_event(
    request: Request,
    event_service: EventService = Depends(get_event_service),
    _: None = Depends(verify_web_auth),
):
    """Create new event from form data and redirect to listing."""
    form_data = await request.form()
    try:
        event = await event_service.create_event(
            title=str(form_data["title"]),
            when=datetime.fromisoformat(str(form_data["when"])),
            place=str(form_data["place"]),
            price=(float(form_data["price"]) if form_data.get("price") else None),
            description=str(form_data.get("description", "") or None),
        )
        return RedirectResponse(url="/events?created=1", status_code=302)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/events/{event_id}")
async def delete_event(
    event_id: str,
    event_service: EventService = Depends(get_event_service),
    _: None = Depends(verify_web_auth),
):
    """Delete event by id, returning JSON result."""
    success = await event_service.delete_event(event_id)
    if not success:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"message": "Event deleted"}



@app.get("/metrics", response_class=HTMLResponse)
async def web_metrics(request: Request, metrics = Depends(get_metrics_service), _: None = Depends(verify_web_auth)):
    overview = metrics.today_overview()
    daily = metrics.daily_summaries(days=14)
    retention = metrics.retention_next_day(days=14)
    features = metrics.feature_usage(days=14, top_n=50)
    demographics = metrics.demographics()
    return templates.TemplateResponse("metrics.html", {
        "request": request,
        "overview": overview,
        "daily": daily,
        "retention": retention,
        "features": features,
        "demographics": demographics,
    })



@app.post("/bookings/delete")
async def web_bookings_delete(request: Request, _: None = Depends(verify_web_auth)):
    data = await request.form()
    booking_id = str(data.get("id") or "").strip()
    if booking_id:
        logger.info("Web: bookings/delete id=%s", booking_id)
        try:
            container.calendar_service().admin_delete_booking(booking_id)
        except Exception:
            # Ignore errors for idempotency
            pass
    return RedirectResponse(url="/bookings?deleted=1", status_code=302)



def parse_title_code_lines(text: str) -> list[dict]:
    """Parse user input lines into list of {title, code} dicts.
    Each non-empty line may be either "Title|code" or a single title (code auto-generated).
    """
    items: list[dict] = []
    for line in str(text).splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            title, code = line.split("|", 1)
        else:
            title, code = line, line.lower().replace(" ", "_")
        title = title.strip()
        code = code.strip()
        if title and code:
            items.append({"title": title, "code": code})
    return items
