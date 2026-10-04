"""The JSON API. One endpoint per thing the browser needs, kept out of app.py."""

import pathlib

from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from .. import backends, coach, history, profile, settings, store
from ..modes import discover
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


async def get_modes(_request):
    return JSONResponse(
        [
            {
                "name": name,
                "help": module.HELP,
                "endpoint": module.ENDPOINT,
                "partner": partner(name),
            }
            for name, module in sorted(MODES.items())
        ]
    )


async def get_backends(request):
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


async def get_profile(_request):
    return JSONResponse({"fields": profile.as_form(), "isSet": profile.is_set()})


async def save_profile(request):
    profile.save(await request.json())
    return JSONResponse({"ok": True})


async def get_settings(_request):
    choices = {
        "tts_voice": models.voice_names(),
        "coach_backend": ("off", *backends.BY_KEY),
    }
    return JSONResponse(settings.as_form(choices) + prompt_fields())


async def save_settings(request):
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


async def get_sessions(request):
    before = request.query_params.get("before")
    return JSONResponse(history.sessions(before=int(before) if before else None))


async def get_session(request):
    found = history.detail(int(request.path_params["session"]))
    if found is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    coaching = "pending" if coach.pending(found["id"]) else "on" if coach.endpoint() else "off"
    return JSONResponse({**found, "partner": partner(found["mode"]), "coaching": coaching})


async def coach_session(request):
    """Notes for answers that have none, then the summary. Old sessions get a report too."""
    coach.catch_up(int(request.path_params["session"]))
    return JSONResponse({"ok": True})


async def get_progress(_request):
    return JSONResponse(
        {"totals": history.totals(), "trend": history.trend(), "mistakes": history.mistakes(7)}
    )


async def get_audio(request):
    path = store.audio_path(int(request.path_params["turn"]))
    if not path or not pathlib.Path(path).exists():
        return JSONResponse({"error": "recording expired or deleted"}, status_code=404)
    return FileResponse(path, media_type="audio/wav")


async def forget(_request):
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
    Route("/api/progress", get_progress),
    Route("/api/audio/{turn:int}", get_audio),
    Route("/api/forget", forget, methods=["POST"]),
]
