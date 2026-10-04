"""Starlette app: static files, the JSON API, and one WebSocket per session."""

import contextlib
import pathlib

from starlette.applications import Starlette
from starlette.responses import FileResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

from .. import backends, llm, settings, store
from . import models
from .api import MODES, ROUTES
from .session import BrowserIO, SessionClosed

WEB = pathlib.Path(__file__).resolve().parents[3] / "web"


async def page(_request):
    """Every non-API path serves the app; the browser routes from there."""
    return FileResponse(WEB / "index.html")


async def websocket_session(websocket):
    """One connection, one session, one mode loop."""
    await websocket.accept()
    session = None
    try:
        opening = await websocket.receive_json()
        mode = MODES[opening["mode"]]
        backend = backends.BY_KEY[opening["backend"]]
        endpoint = llm.endpoint_for(backend)
        resumed = opening.get("resume")
        session = (resumed and store.resume(int(resumed))) or store.start(
            opening["mode"], backend.key, endpoint.model
        )
        io = BrowserIO(websocket, models.voice(), models.transcriber(), session)
        await io.send(
            type="ready",
            mode=opening["mode"],
            model=endpoint.model,
            local=backend.local,
            session=session,
            answered=len(store.session_scores(session)),
        )
        await mode.run(endpoint, io)
    except SessionClosed:
        pass
    except Exception as exc:  # a mode blew up; tell the user rather than dying silently
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "text": str(exc)})
    finally:
        if session is not None:
            store.finish(session)


@contextlib.asynccontextmanager
async def lifespan(_app):
    """Load the models once, before the first request."""
    purged = store.purge_audio(settings.get("audio_retention_days"))
    if purged:
        print(f"  purged {purged} expired recording(s)")
    models.load()
    print("  ready\n")
    yield


app = Starlette(
    lifespan=lifespan,
    routes=[
        *ROUTES,
        WebSocketRoute("/ws", websocket_session),
        Mount("/static", StaticFiles(directory=WEB), name="static"),
        # Last, so it only catches what nothing above claimed: the client's own routes
        # (/profile, /history/3, ...) must survive a reload and a pasted link.
        Route("/{path:path}", page),
    ],
)
