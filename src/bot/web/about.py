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
    return render(request, "about.html", {
        "config": config,
        "photo": config.get("photo"),
        "cinema_photos": cinema_photos
    }, flags=flags)

@router.post("/save")
async def web_about_save(
    photo: UploadFile = File(None),
    about_repo: AboutRepository = Depends(get_about_repository)
):
    from .common import ROOT_DIR
    dst = ROOT_DIR / "data"
    name = await save_upload(photo, dst)
    if name:
        await about_repo.set_photo(name)
    return RedirectResponse(url="/about?saved=1", status_code=303)

@router.post("/cinema/add")
async def web_about_cinema_add(
    photos: list[UploadFile] = File(...),
    about_repo: AboutRepository = Depends(get_about_repository)
):
    from .common import ROOT_DIR
    dst = ROOT_DIR / "data" / "cinema"
    for photo in photos:
        name = await save_upload(photo, dst)
        if name:
            await about_repo.add_cinema_photo(f"cinema/{name}")
    return RedirectResponse(url="/about?added=1", status_code=303)

@router.get("/cinema/delete/{name:path}")
async def web_about_cinema_delete(
    name: str,
    about_repo: AboutRepository = Depends(get_about_repository)
):
    await about_repo.remove_cinema_photo(name)
    return RedirectResponse(url="/about?deleted=1", status_code=303)
