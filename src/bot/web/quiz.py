from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from ...services.repositories import QuizRepository
from ..dependencies import verify_web_auth, get_quiz_service
from .common import render
from .utils import parse_title_code_lines

router = APIRouter(prefix="/quiz", tags=["quiz"], dependencies=[Depends(verify_web_auth)])

@router.get("")
async def web_quiz(request: Request, quiz_repo: QuizRepository = Depends(get_quiz_service)):
    config = await quiz_repo.get_config()
    moods = config.get("moods") or []
    companies = config.get("companies") or []
    recs = config.get("recs") or {}
    
    moods_text = "\n".join([f"{m.get('title')}|{m.get('code')}" for m in moods if isinstance(m, dict)])
    companies_text = "\n".join([f"{c.get('title')}|{c.get('code')}" for c in companies if isinstance(c, dict)])
    
    return render(request, "quiz.html", {
        "moods": moods,
        "companies": companies,
        "recs": recs,
        "moods_text": moods_text,
        "companies_text": companies_text
    })

@router.post("/save")
async def web_quiz_save(request: Request, quiz_repo: QuizRepository = Depends(get_quiz_service)):
    form = await request.form()
    
    moods_raw = str(form.get("moods") or "")
    companies_raw = str(form.get("companies") or "")
    
    moods = parse_title_code_lines(moods_raw)
    companies = parse_title_code_lines(companies_raw)
    
    recs = {}
    for m in moods:
        m_code = m.get("code")
        if not m_code:
            continue
        for c in companies:
            c_code = c.get("code")
            if not c_code:
                continue
            key = f"{m_code}|{c_code}"
            val = str(form.get(f"rec:{key}") or "").strip()
            if val:
                recs[key] = [line.strip() for line in val.splitlines() if line.strip()]
            else:
                recs[key] = []
                
    await quiz_repo.save_config({"moods": moods, "companies": companies, "recs": recs})
    return RedirectResponse(url="/quiz?saved=1", status_code=303)
