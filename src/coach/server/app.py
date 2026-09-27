"""Starlette app: static files, a small JSON API, and one WebSocket per session."""

import contextlib
import pathlib

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

from .. import backends, llm, settings, store, stt, tts
from ..modes import discover
from .session import BrowserIO, SessionClosed

WEB = pathlib.Path(__file__).resolve().parents[3] / "web"
MODES = discover()

_models: dict = {}  # Whisper and Kokoro, loaded once at startup


def prompt_fields() -> list[dict]:
    """Every editable prompt, discovered from the mode modules that own the defaults."""
    fields = []
    for name, module in sorted(MODES.items()):
        for attribute in [a for a in dir(module) if a == "PROMPT" or a.endswith("_PROMPT")]:
            default = getattr(module, attribute)
            key = name if attribute == "PROMPT" else f"{name}:{attribute.lower()}"
            label = name.title() if attribute == "PROMPT" else f"{name.title()} critique"
            fields.append(
                {
                    "key": f"prompt:{key}",
                    "label": label,
                    "group": "Prompts",
                    "kind": "textarea",
                    "value": settings.prompt(key, default),
                    "isDefault": settings.prompt(key, default) == default,
                    "default": default,
                }
            )
    return fields


async def get_modes(_request):
    return JSONResponse(
        [
            {"name": name, "help": module.HELP, "endpoint": module.ENDPOINT}
            for name, module in sorted(MODES.items())
        ]
    )


async def get_backends(request):
    role = request.query_params.get("role", "fast")
    rows, available = backends.survey(role)
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


async def get_settings(_request):
    voices = _models["voice"].names() if "voice" in _models else ()
    return JSONResponse(settings.as_form(voices) + prompt_fields())


async def save_settings(request):
    for key, value in (await request.json()).items():
        if key.startswith("prompt:"):
            settings.set_prompt(key[len("prompt:") :], value)
        elif key in settings.SPEC:
            if settings.SPEC[key].secret and value == "":
                continue  # blank means "leave the stored secret alone"
            settings.set(key, value)
    return JSONResponse({"ok": True})


async def get_trend(_request):
    return JSONResponse(store.trend(limit=int(_request.query_params.get("limit", 30))))


async def get_audio(request):
    path = store.audio_path(int(request.path_params["turn"]))
    if not path or not pathlib.Path(path).exists():
        return JSONResponse({"error": "recording expired or deleted"}, status_code=404)
    return FileResponse(path, media_type="audio/wav")


async def forget(_request):
    store.forget_everything()
    return JSONResponse({"ok": True})


async def index(_request):
    return FileResponse(WEB / "index.html")


async def websocket_session(websocket):
    """One connection, one session, one mode loop."""
    await websocket.accept()
    try:
        opening = await websocket.receive_json()
        mode = MODES[opening["mode"]]
        backend = backends.BY_KEY[opening["backend"]]
        endpoint = llm.endpoint_for(backend)
        store.start(opening["mode"], backend.key, endpoint.model)
        io = BrowserIO(websocket, _models["voice"])
        await io.send(type="ready", mode=opening["mode"], model=endpoint.model, local=backend.local)
        await mode.run(endpoint, _models["stt"], io)
    except SessionClosed:
        pass
    except Exception as exc:  # a mode blew up; tell the user rather than dying silently
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "text": str(exc)})
    finally:
        store.finish()


@contextlib.asynccontextmanager
async def lifespan(_app):
    """Load the models once, before the first request. Starlette 1.x wants a lifespan."""
    purged = store.purge_audio(settings.get("audio_retention_days"))
    if purged:
        print(f"  purged {purged} expired recording(s)")
    print("  loading Whisper...")
    _models["stt"] = stt.Transcriber()
    print("  loading Kokoro...")
    _models["voice"] = tts.Voice()
    print("  ready\n")
    yield


app = Starlette(
    lifespan=lifespan,
    routes=[
        Route("/", index),
        Route("/api/modes", get_modes),
        Route("/api/backends", get_backends),
        Route("/api/settings", get_settings, methods=["GET"]),
        Route("/api/settings", save_settings, methods=["POST"]),
        Route("/api/trend", get_trend),
        Route("/api/audio/{turn:int}", get_audio),
        Route("/api/forget", forget, methods=["POST"]),
        WebSocketRoute("/ws", websocket_session),
        Mount("/static", StaticFiles(directory=WEB), name="static"),
    ],
)
