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
    questions = await quiz_repo.list_all()
    return render(request, "quiz.html", {"questions": questions})

@router.post("/save")
async def web_quiz_save(request: Request, quiz_repo: QuizRepository = Depends(get_quiz_service)):
    form = await request.form()
    # Simplified logic: read all questions and save
    # [Logic from webapp.py 534-555]
    raw_qs = form.getlist("question[]")
    raw_as = form.getlist("answer[]")
    
    questions = []
    for i in range(len(raw_qs)):
        q = str(raw_qs[i]).strip()
        a = str(raw_as[i]).strip() if i < len(raw_as) else ""
        if q:
            questions.append({"question": q, "answer": a})
            
    await quiz_repo.save_all(questions)
    return RedirectResponse(url="/quiz?saved=1", status_code=303)
