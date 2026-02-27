from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from ...services.repositories import ScheduleRepository, LocationRepository
from ..dependencies import verify_web_auth, get_schedule_repository, get_location_service
from .common import render, QueryFlags

router = APIRouter(prefix="/schedule", tags=["schedule"], dependencies=[Depends(verify_web_auth)])

@router.get("")
async def web_schedule(
    request: Request,
    sched_repo: ScheduleRepository = Depends(get_schedule_repository),
    loc_repo: LocationRepository = Depends(get_location_service),
    flags: QueryFlags = Depends()
):
    from ...services.models import SessionType
    rules = await sched_repo.get_all()
    models = await loc_repo.get_all()
    locs = [l.name for l in models]
    stypes = [t.value for t in SessionType]
    
    return render(request, "schedule.html", {
        "rules": rules, 
        "locations": locs, 
        "session_types": stypes
    }, flags=flags)

@router.post("/save")
async def web_schedule_save(
    request: Request,
    sched_repo: ScheduleRepository = Depends(get_schedule_repository)
):
    form = await request.form()
    
    # Extract lists from form
    ids = form.getlist("id")
    day_of_weeks = form.getlist("day_of_week")
    starts = form.getlist("start")
    ends = form.getlist("end")
    durations = form.getlist("duration")
    intervals = form.getlist("interval")
    locations = form.getlist("location")
    session_types = form.getlist("session_type")
    deleteds = form.getlist("deleted")
    
    new_rules = []
    # All fields should have same length, but we use day_of_weeks as primary driver
    for i in range(len(day_of_weeks)):
        # Construct rule dict; ScheduleRule.model_validate handles conversion
        rule = {
            "id": str(ids[i]) if i < len(ids) and ids[i] else None,
            "day_of_week": int(day_of_weeks[i]),
            "start": str(starts[i]) if i < len(starts) else "",
            "end": str(ends[i]) if i < len(ends) else "",
            "duration": int(durations[i]) if i < len(durations) and durations[i] else 50,
            "interval": int(intervals[i]) if i < len(intervals) and intervals[i] else None,
            "location": str(locations[i]) if i < len(locations) else "",
            "session_type": str(session_types[i]) if i < len(session_types) else "",
            "deleted": deleteds[i] == "1" if i < len(deleteds) else False,
        }
        new_rules.append(rule)
        
    await sched_repo.save_all(new_rules)
    return RedirectResponse(url="/schedule?saved=1", status_code=303)
