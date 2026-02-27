from __future__ import annotations

import base64
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse

from ...services.repositories import LocationRepository, SessionLocationsRepository
from ..dependencies import verify_web_auth, get_location_service, get_session_locations_repository
from .common import render, QueryFlags
from .utils import LocationCreate, location_form

router = APIRouter(prefix="/locations", tags=["locations"], dependencies=[Depends(verify_web_auth)])

@router.get("")
async def web_locations(
    request: Request,
    loc_repo: LocationRepository = Depends(get_location_service),
    flags: QueryFlags = Depends()
):
    locs = await loc_repo.list_all()
    return render(request, "locations.html", {"locations": locs}, flags=flags)

@router.post("/add")
async def web_locations_add(
    name: str = Form(...),
    loc_repo: LocationRepository = Depends(get_location_service)
):
    await loc_repo.add(name.strip())
    return RedirectResponse(url="/locations?added=1", status_code=303)

@router.post("/delete/{name}")
async def web_locations_delete(
    name: str,
    loc_repo: LocationRepository = Depends(get_location_service)
):
    await loc_repo.remove(name)
    return RedirectResponse(url="/locations?deleted=1", status_code=303)

@router.get("/by-type")
async def web_locations_by_type(
    request: Request,
    repo: SessionLocationsRepository = Depends(get_session_locations_repository),
    loc_repo: LocationRepository = Depends(get_location_service),
    flags: QueryFlags = Depends()
):
    types = ["cinema", "individual", "group", "online"]
    data = {}
    for t in types:
        data[t] = await repo.list_for(t)
    locs = await loc_repo.list_all()
    return render(request, "locations_by_type.html", {"data": data, "locations": locs}, flags=flags)

@router.post("/by-type/add")
async def web_locations_by_type_add(
    request: Request,
    repo: SessionLocationsRepository = Depends(get_session_locations_repository)
):
    form = await request.form()
    stype = str(form.get("type", ""))
    val = str(form.get("location", ""))
    if stype and val:
        await repo.add(stype, val)
    return RedirectResponse(url=f"/locations/by-type?added=1", status_code=303)

@router.post("/by-type/delete/{type_enc}/{val_enc}")
async def web_locations_by_type_del(
    type_enc: str,
    val_enc: str,
    repo: SessionLocationsRepository = Depends(get_session_locations_repository)
):
    def b64_decode(s: str) -> str:
        pad = "=" * (-len(s) % 4)
        return base64.urlsafe_b64decode((s + pad).encode("ascii")).decode("utf-8")
        
    stype = b64_decode(type_enc)
    val = b64_decode(val_enc)
    await repo.remove(stype, val)
    return RedirectResponse(url="/locations/by-type?deleted=1", status_code=303)
