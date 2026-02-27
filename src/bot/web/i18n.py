from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from ..dependencies import verify_web_auth
from .common import render, QueryFlags
from ...i18n.texts import RU, EN
from ...services.storage import read_json, write_json
from pathlib import Path

router = APIRouter(prefix="/i18n", tags=["i18n"], dependencies=[Depends(verify_web_auth)])

ROOT_DIR = Path(__file__).resolve().parents[2]
TEXTS_PATH = (ROOT_DIR / "data" / "texts.json")

def _read_texts_overrides() -> dict:
    try:
        data = read_json(TEXTS_PATH, default={})
        if not isinstance(data, dict):
            return {"RU": {}, "EN": {}}
        return {"RU": dict(data.get("RU", {})), "EN": dict(data.get("EN", {}))}
    except Exception:
        return {"RU": {}, "EN": {}}

def _write_texts_overrides(data: dict) -> None:
    TEXTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(TEXTS_PATH, data)

@router.get("")
async def web_i18n(request: Request, flags: QueryFlags = Depends()):
    overrides = _read_texts_overrides()
    keys = sorted(set(list(RU.keys()) + list(EN.keys())))
    
    items = []
    for k in keys:
        items.append({
            "key": k,
            "ru_orig": RU.get(k, ""),
            "en_orig": EN.get(k, ""),
            "ru_over": overrides["RU"].get(k, ""),
            "en_over": overrides["EN"].get(k, ""),
        })
    return render(request, "i18n.html", {"items": items}, flags=flags)

@router.post("/save")
async def web_i18n_save(request: Request):
    form = await request.form()
    keys = form.getlist("key[]")
    ru_overs = form.getlist("ru[]")
    en_overs = form.getlist("en[]")
    
    overrides = {"RU": {}, "EN": {}}
    for i in range(len(keys)):
        k = str(keys[i])
        ru = str(ru_overs[i]).strip() if i < len(ru_overs) else ""
        en = str(en_overs[i]).strip() if i < len(en_overs) else ""
        if ru: overrides["RU"][k] = ru
        if en: overrides["EN"][k] = en
            
    _write_texts_overrides(overrides)
    return RedirectResponse(url="/i18n?saved=1", status_code=303)
