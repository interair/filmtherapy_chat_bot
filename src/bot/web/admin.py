from __future__ import annotations

from fastapi import APIRouter, Depends, Request
import asyncio
from ...services.metrics_service import MetricsService
from ..dependencies import verify_web_auth, get_metrics_service
from .common import render, QueryFlags
from .utils import compute_new_bookings_today

router = APIRouter(prefix="", tags=["admin"], dependencies=[Depends(verify_web_auth)])

@router.get("/")
async def web_index(request: Request, metrics: MetricsService = Depends(get_metrics_service), flags: QueryFlags = Depends()):
    overview_task = metrics.today_overview()
    top_features_task = metrics.feature_usage(days=7, top_n=3)
    new_bookings_task = compute_new_bookings_today()
    
    overview, top_features, new_bookings_today = await asyncio.gather(
        overview_task, top_features_task, new_bookings_task
    )
    
    return render(request, "index.html", {
        "metrics_overview": overview,
        "top_features": top_features,
        "new_bookings_today": new_bookings_today,
    }, flags=flags)

@router.get("/system")
async def web_system(request: Request):
    import platform
    import sys
    sys_info = {
        "os": platform.system(),
        "release": platform.release(),
        "python": sys.version,
        "arch": platform.machine(),
    }
    return render(request, "system.html", {"sys_info": sys_info})

@router.get("/metrics")
async def web_metrics(request: Request, metrics: MetricsService = Depends(get_metrics_service)):
    usage = await metrics.feature_usage(days=30)
    return render(request, "metrics.html", {"usage": usage})

@router.get("/health", tags=["system"], include_in_schema=True)
async def health_check():
    """Health check endpoint for container orchestrators."""
    return {"status": "ok", "timestamp": "now"}
