"""The JSON API. One endpoint per thing the browser needs, kept out of app.py."""

import asyncio
import datetime as dt

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .. import (
    backends,
    documents,
    history,
    jobs,
    machine,
    profile,
    relay,
    settings,
    store,
    today,
)
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
                "interview": getattr(module, "INTERVIEW", False),
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
    return JSONResponse(
        {
            "fields": profile.as_form(),
            "isSet": profile.is_set(),
            "resume": bool(profile.get("resume").strip()),
        }
    )


async def save_profile(request: Request) -> Response:
    profile.save(await request.json())
    return JSONResponse({"ok": True})


async def extract(request: Request) -> Response:
    """The text of an uploaded resume or job posting, for the profile form to show before it
    is saved. The file is the whole body, so there is no multipart parser to depend on."""
    data = await request.body()
    if len(data) > documents.MAX_BYTES:
        return JSONResponse({"error": "That file is over 5MB."}, status_code=413)
    try:
        text = await asyncio.to_thread(documents.text, request.query_params.get("name", ""), data)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"text": text})


async def get_jobs(request: Request) -> Response:
    """Real postings to practise for. Software engineering unless the page asks for
    something else: that is what the interview modes interview for."""
    ask = request.query_params
    words = ask.get("q") or "software engineer"
    seniority = ask.get("seniority", "")
    page = ask.get("page", "1")
    try:
        found = await asyncio.to_thread(
            jobs.search,
            words,
            seniority,
            ask.get("country", "").strip(),
            ask.get("worldwide") == "1",
            int(page) if page.isdigit() else 1,
        )
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    return JSONResponse({**found, "q": words, "seniority": seniority})


async def get_machine(_request: Request) -> Response:
    return JSONResponse(
        {**machine.specs(), "model_gb": machine.room(), "lm_studio": machine.lm_studio_host()}
    )


async def get_settings(_request: Request) -> Response:
    models_that_fit = {
        key: backends.choices(settings.get(key))
        for key in ("coach_backend", "sheet_backend", "verdict_backend")
    }
    choices = {"tts_voice": models.voice_names(), **models_that_fit}
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
    """Today's practice, and what is wired up: a Telegram that is off must not look broken."""
    wired = {
        "gemini": bool(settings.api_key()),
        "telegram": relay.missing(),
        "to": relay.recipient(),
        "problem": relay.problem,
    }
    return JSONResponse({**today.summary(dt.date.today()), "wired": wired})


async def forget(_request: Request) -> Response:
    store.forget_everything()
    return JSONResponse({"ok": True})


ROUTES = [
    Route("/api/modes", get_modes),
    Route("/api/backends", get_backends),
    Route("/api/machine", get_machine),
    Route("/api/profile", get_profile, methods=["GET"]),
    Route("/api/profile", save_profile, methods=["POST"]),
    Route("/api/extract", extract, methods=["POST"]),
    Route("/api/jobs", get_jobs),
    Route("/api/settings", get_settings, methods=["GET"]),
    Route("/api/settings", save_settings, methods=["POST"]),
    Route("/api/progress", get_progress),
    Route("/api/today", get_today),
    Route("/api/forget", forget, methods=["POST"]),
]
