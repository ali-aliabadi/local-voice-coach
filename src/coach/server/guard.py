"""Only a browser on this machine, on this app's own pages, may use the server.

The server listens on localhost, but every website you visit can still send requests to
localhost. Without this, any page could POST /api/forget and wipe your history, or point
the LM Studio URL at itself so your transcripts go there. A DNS-rebinding page - its own
domain resolving to 127.0.0.1 - could even read /api/sessions and fetch your recordings.

Two checks close that: the Host header must be this machine (Starlette's
TrustedHostMiddleware, which stops rebinding), and anything that changes state - a POST,
or opening the practice socket - must come from one of our own pages (the Origin check
below, which stops cross-site requests). Clients that send no Origin, like curl or the
tests, are local processes and are let through.
"""

import os
from urllib.parse import urlsplit

from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# ALLOWED_HOSTS adds names for serving beyond localhost, e.g. a Tailscale https name.
HOSTS = ["127.0.0.1", "localhost", "::1", "[::1]"] + [
    h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()
]
SAFE = ("GET", "HEAD", "OPTIONS")


def foreign(origin: str) -> bool:
    """True for an Origin that is not one of our hosts. No Origin at all is not foreign."""
    return bool(origin) and urlsplit(origin).hostname not in HOSTS


class SameOrigin:
    """Reject state-changing requests from other sites, and stop the browser serving a
    stale copy of the app after an update (no-cache revalidates; it is free on localhost)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        origin = dict(scope["headers"]).get(b"origin", b"").decode()
        if scope["type"] == "websocket" and foreign(origin):
            await receive()  # the connect event, then refuse it
            return await send({"type": "websocket.close", "code": 1008})
        if scope["type"] == "http" and scope["method"] not in SAFE and foreign(origin):
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [(b"content-type", b"text/plain")],
                }
            )
            return await send({"type": "http.response.body", "body": b"Cross-site request"})

        async def no_cache(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), (b"cache-control", b"no-cache")]
            await send(message)

        return await self.app(scope, receive, no_cache if scope["type"] == "http" else send)


MIDDLEWARE = [Middleware(TrustedHostMiddleware, allowed_hosts=HOSTS), Middleware(SameOrigin)]
