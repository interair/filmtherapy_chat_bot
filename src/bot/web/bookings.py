from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from ...services.calendar_service import CalendarService
from ..dependencies import verify_web_auth, get_calendar_service
from .common import render, QueryFlags
from .utils import BookingView

router = APIRouter(prefix="/bookings", tags=["bookings"], dependencies=[Depends(verify_web_auth)])

@router.get("")
async def web_bookings(
    request: Request,
    calendar_service: CalendarService = Depends(get_calendar_service),
    flags: QueryFlags = Depends()
):
    raw = await calendar_service.list_all_bookings()
    items = BookingView.list_from_raw(raw)
    return render(request, "bookings.html", {"items": items}, flags=flags)

@router.post("/delete")
async def web_bookings_delete(
    request: Request,
    calendar_service: CalendarService = Depends(get_calendar_service)
):
    form = await request.form()
    booking_id = str(form.get("id", ""))
    if booking_id:
        await calendar_service.delete_booking(booking_id)
    return RedirectResponse(url="/bookings?deleted=1", status_code=303)
