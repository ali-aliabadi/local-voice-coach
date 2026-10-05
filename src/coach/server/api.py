"""The JSON API. One endpoint per thing the browser needs, kept out of app.py."""

import datetime as dt
import pathlib

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from .. import backends, coach, history, llm, profile, reports, settings, sheet, store, today
from ..modes import discover, state, unlock
from . import models

MODES = discover()


def prompt_fields() -> list[dict]:
    """Every editable prompt, discovered from the mode modules that own the defaults."""
    fields = []
    for name, module in sorted(MODES.items()):
        for attribute in [a for a in dir(module) if a == "PROMPT" or a.endswith("_PROMPT")]:
            default = getattr(module, attribute)
            key = name if attribute == "PROMPT" else f"{name}:{attribute.lower()}"
            current = settings.prompt(key, default)
            fields.append(
                {
                    "key": f"prompt:{key}",
                    "group": "Prompts",
                    "kind": "textarea",
                    "label": name.title() if attribute == "PROMPT" else f"{name.title()} critique",
                    "value": current,
                    "isDefault": current == default,
                    "default": default,
                }
            )
    return fields


def partner(mode: str) -> str:
    """Who the user talks to in a mode, as the pages name them."""
    return getattr(MODES.get(mode), "PARTNER", "interviewer")


async def get_modes(_request: Request) -> Response:
    done = history.count()
    return JSONResponse(
        [
            {
                "name": name,
                "help": module.HELP,
                "endpoint": module.ENDPOINT,
                "partner": partner(name),
                "unlock": unlock(module),
                "state": state(module, done),
                "left": max(0, unlock(module) - done),
            }
            for name, module in sorted(MODES.items(), key=lambda kv: (unlock(kv[1]), kv[0]))
        ]
    )


async def get_backends(request: Request) -> Response:
    rows, available = backends.survey(request.query_params.get("role", "fast"))
    measured = store.measured_latency()
    return JSONResponse(
        {
            "available": available,
            "backends": [
                {
                    **backend._asdict(),
                    "blocked": blocked,
                    "measured_ms": measured.get(backend.key, (None, 0))[0],
                    "samples": measured.get(backend.key, (None, 0))[1],
                }
                for backend, blocked in rows
            ],
        }
    )


async def get_profile(_request: Request) -> Response:
    return JSONResponse({"fields": profile.as_form(), "isSet": profile.is_set()})


async def save_profile(request: Request) -> Response:
    profile.save(await request.json())
    return JSONResponse({"ok": True})


async def get_settings(_request: Request) -> Response:
    choices = {
        "tts_voice": models.voice_names(),
        "coach_backend": ("off", *backends.BY_KEY),
        "sheet_backend": ("off", *backends.BY_KEY),
    }
    return JSONResponse(settings.as_form(choices) + prompt_fields())


async def save_settings(request: Request) -> Response:
    defaults = {f["key"]: f["default"] for f in prompt_fields()}
    for key, value in (await request.json()).items():
        if key.startswith("prompt:"):
            settings.set_prompt(key[len("prompt:") :], value, defaults.get(key))
        elif key in settings.SPEC:
            if settings.SPEC[key].secret and value == "":
                continue  # blank means "leave the stored secret alone"
            try:
                settings.set(key, value)
            except ValueError:
                return JSONResponse({"error": f"{key}: not a valid number"}, status_code=400)
    return JSONResponse({"ok": True})


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
    """Notes for answers that have none, then the summary. Old sessions get a report too."""
    coach.catch_up(int(request.path_params["session"]))
    return JSONResponse({"ok": True})


async def get_progress(_request: Request) -> Response:
    day = lambda back: (dt.date.today() - dt.timedelta(days=back)).isoformat()  # noqa: E731
    return JSONResponse(
        {
            "totals": history.totals(),
            "trend": history.trend(),
            "mistakes": history.mistakes(7),
            "listening": {
                "week": history.listening(day(6), day(0)),
                "before": history.listening(day(13), day(7)),
            },
        }
    )


async def get_today(_request: Request) -> Response:
    return JSONResponse(today.summary(dt.date.today()))


async def get_audio(request: Request) -> Response:
    path = store.audio_path(int(request.path_params["turn"]))
    if not path or not pathlib.Path(path).exists():
        return JSONResponse({"error": "recording expired or deleted"}, status_code=404)
    return FileResponse(path, media_type="audio/wav")


async def forget(_request: Request) -> Response:
    store.forget_everything()
    return JSONResponse({"ok": True})


ROUTES = [
    Route("/api/modes", get_modes),
    Route("/api/backends", get_backends),
    Route("/api/profile", get_profile, methods=["GET"]),
    Route("/api/profile", save_profile, methods=["POST"]),
    Route("/api/settings", get_settings, methods=["GET"]),
    Route("/api/settings", save_settings, methods=["POST"]),
    Route("/api/sessions", get_sessions),
    Route("/api/sessions/{session:int}", get_session),
    Route("/api/sessions/{session:int}/coach", coach_session, methods=["POST"]),
    Route("/api/sessions/{session:int}/sheet", write_sheet, methods=["POST"]),
    Route("/api/sessions/{session:int}/sheet.pdf", get_sheet),
    Route("/api/progress", get_progress),
    Route("/api/today", get_today),
    Route("/api/audio/{turn:int}", get_audio),
    Route("/api/forget", forget, methods=["POST"]),
]
