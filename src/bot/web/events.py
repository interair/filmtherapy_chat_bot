from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import RedirectResponse

from ...services.repositories import LocationRepository, EventRepository
from ...services.event_service import EventService
from ..dependencies import verify_web_auth, get_location_service, get_event_registration_repository, get_event_repository, get_event_service
from .common import render
from .utils import save_upload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/events", tags=["events"], dependencies=[Depends(verify_web_auth)])

@router.get("")
async def web_events(
    request: Request,
    show_past: bool = False,
    event_service: EventService = Depends(get_event_service),
    reg_repo = Depends(get_event_registration_repository),
):
    if show_past:
        events = await event_service.list_past_events()
    else:
        events = await event_service.list_upcoming_events()
        
    attendees = {}
    for ev in events:
        regs = await reg_repo.get_by_event(ev.id)
        attendees[ev.id] = regs
    
    return render(request, "events.html", {
        "poster": events, 
        "attendees": attendees,
        "show_past": show_past
    })

@router.get("/add")
async def web_events_add(request: Request, loc_repo: LocationRepository = Depends(get_location_service)):
    models = await loc_repo.get_all()
    locs = [l.name for l in models]
    return render(request, "events_add.html", {"locs": locs})

@router.get("/edit/{id}")
async def web_events_edit(
    id: str,
    request: Request,
    event_repo: EventRepository = Depends(get_event_repository),
    loc_repo: LocationRepository = Depends(get_location_service)
):
    ev = await event_repo.get_by_id(id)
    models = await loc_repo.get_all()
    locs = [l.name for l in models]
    
    when_value = ""
    if ev and ev.when:
        when_value = ev.when.strftime("%Y-%m-%dT%H:%M")
        
    return render(request, "events_edit.html", {
        "event": ev,
        "photo": ev.photo if ev else None,
        "locs": locs, 
        "when_value": when_value
    })

@router.post("/save")
async def web_events_save(
    request: Request,
    photo: UploadFile = File(None),
    event_repo: EventRepository = Depends(get_event_repository)
):
    form = await request.form()
    event_id = str(form.get("id", "")).strip()
    
    # Handle photo upload
    photo_name = None
    if photo and photo.filename:
        from .common import ROOT_DIR
        # Use src/data/ for uploads as it is mounted to /static
        dst = ROOT_DIR / "data"
        photo_name = await save_upload(photo, dst)

    data = {
        "title": str(form.get("title", "")).strip(),
        "description": str(form.get("description", "")).strip(),
        "place": str(form.get("place", "")).strip(),
        "price": float(form.get("price", 0)) if form.get("price") else None,
        "when": datetime.fromisoformat(str(form.get("when", ""))),
    }
    if photo_name:
        data["photo"] = photo_name
    
    try:
        if event_id:
            # Preserve existing photo if not uploading a new one
            existing = await event_repo.get_by_id(event_id)
            if existing and not photo_name:
                data["photo"] = existing.photo
            
            data["id"] = event_id
            await event_repo.update(data)
            return RedirectResponse(url="/events?updated=1", status_code=303)
        else:
            import secrets
            data["id"] = secrets.token_hex(4)
            # Create the event with the photo field (if present)
            logger.info("Creating new event with data: %s", data)
            await event_repo.create(data)
            return RedirectResponse(url="/events?created=1", status_code=303)
    except Exception as e:
        logger.error("Failed to save event: %s", e, exc_info=True)
        return RedirectResponse(url="/events?error=1", status_code=303)

@router.get("/delete/{id}")
async def web_events_delete(id: str, event_service: EventService = Depends(get_event_service)):
    await event_service.delete_event(id)
    return RedirectResponse(url="/events?deleted=1", status_code=303)
