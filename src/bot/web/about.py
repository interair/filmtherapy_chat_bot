from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import RedirectResponse

from ...services.repositories import AboutRepository
from ..dependencies import verify_web_auth, get_about_repository
from .common import render, QueryFlags

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/about", tags=["about"], dependencies=[Depends(verify_web_auth)])

async def save_upload(
    file_field: UploadFile,
    dst_dir: Path,
    allowed_exts: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp"),
) -> str | None:
    if not file_field or not file_field.filename:
        return None
    ext = Path(file_field.filename).suffix.lower()
    if ext not in allowed_exts:
        ext = ".jpg"
    
    import secrets
    name = f"{secrets.token_hex(8)}{ext}"
    dst_dir.mkdir(parents=True, exist_ok=True)
    path = dst_dir / name
    
    try:
        content = await file_field.read()
        path.write_bytes(content)
        return name
    except Exception:
        logger.exception("Failed to save upload")
        return None

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
