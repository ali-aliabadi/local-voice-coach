"""The JSON routes about sessions already done: the history, one session in full, the
coach's work on it afterwards, and its recordings."""

import pathlib

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from .. import coach, history, llm, reports, sheet, store, verdict
from .api import partner


async def get_sessions(request: Request) -> Response:
    before = request.query_params.get("before")
    return JSONResponse(history.sessions(before=int(before) if before else None))


async def get_session(request: Request) -> Response:
    found = history.detail(int(request.path_params["session"]))
    if found is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    coaching = "pending" if coach.pending(found["id"]) else "on" if coach.endpoint() else "off"
    return JSONResponse(
        {
            **found,
            "partner": partner(found["mode"]),
            "coaching": coaching,
            "coach_error": coach.failed.get(found["id"]),
            "sheet": sheet.stored(found["id"]) is not None,
            "can_sheet": sheet.endpoint() is not None and found["answers"] >= sheet.MIN_ANSWERS,
            "counted": history.is_counted(found["id"]),
            "minimum": {"answers": history.MIN_ANSWERS, "minutes": history.MIN_MINUTES},
            "telegram": reports.sent(found["id"], found["answers"]),
            "interview": verdict.is_interview(found["id"]),
            "can_verdict": verdict.endpoint() is not None,
            "waiting": llm.waiting,
        }
    )


async def write_sheet(request: Request) -> Response:
    """(Re)write a session's study sheet in the background."""
    sheet.later(int(request.path_params["session"]))
    return JSONResponse({"ok": True})


async def get_sheet(request: Request) -> Response:
    """The study sheet as a PDF, drawn fresh from what the model wrote."""
    session_id = int(request.path_params["session"])
    doc = sheet.render(session_id)
    if doc is None:
        return JSONResponse({"error": "no study sheet for this session yet"}, status_code=404)
    name = f"study-sheet-{session_id}.pdf"
    return Response(
        doc.pdf(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )


async def coach_session(request: Request) -> Response:
    """Notes for answers that have none, then the summary, and an interview's verdict.
    Old sessions get a report too."""
    coach.catch_up(int(request.path_params["session"]))
    verdict.later(int(request.path_params["session"]))
    return JSONResponse({"ok": True})


async def get_audio(request: Request) -> Response:
    path = store.audio_path(int(request.path_params["turn"]))
    if not path or not pathlib.Path(path).exists():
        return JSONResponse({"error": "recording expired or deleted"}, status_code=404)
    return FileResponse(path, media_type="audio/wav")


ROUTES = [
    Route("/api/sessions", get_sessions),
    Route("/api/sessions/{session:int}", get_session),
    Route("/api/sessions/{session:int}/coach", coach_session, methods=["POST"]),
    Route("/api/sessions/{session:int}/sheet", write_sheet, methods=["POST"]),
    Route("/api/sessions/{session:int}/sheet.pdf", get_sheet),
    Route("/api/audio/{turn:int}", get_audio),
]
