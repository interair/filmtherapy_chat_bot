from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse

from ...services.event_service import EventService
from ...services.repositories import LocationRepository, EventRepository
from ..dependencies import verify_web_auth, get_event_service, get_location_service, get_event_registration_repository, get_event_repository
from .common import render, QueryFlags

router = APIRouter(prefix="/events", tags=["events"], dependencies=[Depends(verify_web_auth)])

@router.get("")
async def web_events(
    request: Request,
    event_service: EventService = Depends(get_event_service),
    reg_repo = Depends(get_event_registration_repository),
):
    events = await event_service.list_all_events()
    # Parallelize registration counts if possible, but for simplicity:
    enriched = []
    for ev in events:
        regs = await reg_repo.get_by_event(ev.id)
        enriched.append({"event": ev, "reg_count": len(regs)})
    
    return render(request, "events.html", {"events": enriched})

@router.get("/add")
async def web_events_add(request: Request, loc_repo: LocationRepository = Depends(get_location_service)):
    locs = await loc_repo.list_all()
    return render(request, "events_add.html", {"locations": locs})

@router.get("/edit/{id}")
async def web_events_edit(
    id: str,
    request: Request,
    event_repo: EventRepository = Depends(get_event_repository),
    loc_repo: LocationRepository = Depends(get_location_service)
):
    ev = await event_repo.get(id)
    locs = await loc_repo.list_all()
    return render(request, "events_edit.html", {"event": ev, "locations": locs})

@router.post("/save")
async def web_events_save(
    request: Request,
    event_repo: EventRepository = Depends(get_event_repository)
):
    form = await request.form()
    event_id = str(form.get("id", "")).strip()
    data = {
        "title": str(form.get("title", "")),
        "description": str(form.get("description", "")),
        "location_id": str(form.get("location_id", "")),
        "price": str(form.get("price", "")),
        "capacity": int(form.get("capacity", 0)) if form.get("capacity") else None,
        "date": str(form.get("date", "")),
    }
    
    if event_id:
        await event_repo.update(event_id, data)
        return RedirectResponse(url="/events?updated=1", status_code=303)
    else:
        await event_repo.create(data)
        return RedirectResponse(url="/events?created=1", status_code=303)

@router.post("/delete/{id}")
async def web_events_delete(id: str, event_repo: EventRepository = Depends(get_event_repository)):
    await event_repo.delete(id)
    return RedirectResponse(url="/events?deleted=1", status_code=303)
