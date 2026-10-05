"""Starlette app: static files, the JSON API, and one WebSocket per session."""

import asyncio
import contextlib
import pathlib
import signal

from starlette.applications import Starlette
from starlette.responses import FileResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

from .. import backends, clock, coach, history, llm, reports, settings, sheet, store
from . import models
from .api import MODES, ROUTES, partner
from .guard import MIDDLEWARE
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
            opening["mode"], backend.key, endpoint.model, opening.get("goal")
        )
        io = BrowserIO(websocket, models.voice(), models.transcriber(), session)
        await io.send(
            type="ready",
            mode=opening["mode"],
            partner=partner(opening["mode"]),
            model=endpoint.model,
            local=backend.local,
            session=session,
            answered=len(store.session_scores(session)),
            # so a reloaded page picks up the clock, the goal and the session chart
            elapsed=store.elapsed(session),
            goal=store.goal(session),
            answers=history.answers(session),
            so_far=history.so_far(session),
            hands_free=settings.get("hands_free") == "on",
            silence=settings.get("hands_free_silence"),
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
            # Each skips a session too short to count, and waits for the ones before it.
            coach.summarise(session)  # once the notes are in; skipped if already current
            sheet.later(session)  # after the summary: the take-away page
            coach.later(session, reports.after_session(session))  # to Telegram, last


async def finish_up() -> None:
    """The app is stopped as soon as you are done, so quitting must not lose the study
    sheet and the report still being written: wait for them, unless Ctrl-C comes again."""
    tasks = coach.queued()
    if not tasks:
        return
    waiting = asyncio.gather(*tasks, return_exceptions=True)
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, waiting.cancel)
    except NotImplementedError:  # Windows: no way to offer a second Ctrl-C, so do not hold
        return
    print("  finishing the study sheet and report - Ctrl-C again to quit now")
    try:
        await waiting
    except asyncio.CancelledError:
        print("  left unfinished")
    finally:
        loop.remove_signal_handler(signal.SIGINT)


@contextlib.asynccontextmanager
async def lifespan(_app):
    """Load the models once, before the first request, and start the clock."""
    models.load()
    ticking = asyncio.create_task(clock.run())  # expiring recordings now runs from here
    print("  ready\n")
    yield
    ticking.cancel()
    await finish_up()


app = Starlette(
    lifespan=lifespan,
    middleware=MIDDLEWARE,
    routes=[
        *ROUTES,
        WebSocketRoute("/ws", websocket_session),
        Mount("/static", StaticFiles(directory=WEB), name="static"),
        # Last, so it only catches what nothing above claimed: the client's own routes
        # (/profile, /history/3, ...) must survive a reload and a pasted link.
        Route("/{path:path}", page),
    ],
)
