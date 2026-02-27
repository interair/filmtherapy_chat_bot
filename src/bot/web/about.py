from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import RedirectResponse

from ...services.repositories import AboutRepository
from ..dependencies import verify_web_auth, get_about_repository
from .common import render, QueryFlags
from .utils import save_upload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/about", tags=["about"], dependencies=[Depends(verify_web_auth)])

@router.get("")
async def web_about(
    request: Request,
    about_repo: AboutRepository = Depends(get_about_repository),
    flags: QueryFlags = Depends()
):
    config = await about_repo.get_config()
    cinema_photos = await about_repo.list_cinema_photos()
    return render(request, "about.html", {"config": config, "cinema_photos": cinema_photos}, flags=flags)

@router.post("/save")
async def web_about_save(
    request: Request,
    about_repo: AboutRepository = Depends(get_about_repository)
):
    form = await request.form()
    data = {
        "description": str(form.get("description", "")),
        "address": str(form.get("address", "")),
        "how_to_get": str(form.get("how_to_get", "")),
    }
    await about_repo.update_config(data)
    return RedirectResponse(url="/about?saved=1", status_code=303)

@router.post("/cinema/add")
async def web_about_cinema_add(
    file: UploadFile = File(...),
    about_repo: AboutRepository = Depends(get_about_repository)
):
    from .common import ROOT_DIR
    dst = ROOT_DIR / "data" / "cinema"
    name = await save_upload(file, dst)
    if name:
        await about_repo.add_cinema_photo(name)
    return RedirectResponse(url="/about?added=1", status_code=303)

@router.post("/cinema/delete/{name}")
async def web_about_cinema_delete(
    name: str,
    about_repo: AboutRepository = Depends(get_about_repository)
):
    await about_repo.remove_cinema_photo(name)
    return RedirectResponse(url="/about?deleted=1", status_code=303)
