"""Gemini keys: one, or a pool that people sharing a server lend each other.

An admin adds keys on the Settings page, and GEMINI_API_KEY and GEMINI_API_KEYS add more
from the environment (vault.py). A key that is rate-limited, out of quota or rejected
rests, and the request goes again at once on the next one. Only when every key is
resting does the caller see the error, and then `llm.patiently` waits or falls back as
it always has. Each key's free tier is its own, so two keys are twice the requests.

Keys never leave this process except to Gemini, and are never logged: a resting key is
named by its last four characters only.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import openai

from . import vault

if TYPE_CHECKING:
    from .llm import Endpoint

WAIT = re.compile(r"retry in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?")
REJECTED_REST = 24 * 3600  # a rejected key stays rejected; a day, in case it is fixed
SPENT_REST = 15 * 60  # a spending cap says no "retry in"; look again in a while
_resting: dict[str, float] = {}  # key -> time.monotonic() when it may be tried again


def retry_after(message: str) -> float | None:
    """Seconds from "Please retry in 3h35m42.5s" or "retry in 33.8s"; None if not said."""
    found = WAIT.search(message)
    if not found or not any(found.groups()):
        return None
    hours, minutes, seconds = found.groups()
    return int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds or 0)


def pool() -> list[str]:
    """Every key, in order, once: the app's first, then the environment's."""
    return vault.gemini_keys()


def current() -> str:
    """The first key not resting; when all are, the one back soonest; "" with none."""
    keys = pool()
    now = time.monotonic()
    fresh = [k for k in keys if _resting.get(k, 0) <= now]
    if fresh:
        return fresh[0]
    return min(keys, key=lambda k: _resting[k]) if keys else ""


def rest(key: str, exc: Exception) -> None:
    """Set a key aside for as long as its error says, or a sensible while."""
    if isinstance(exc, openai.RateLimitError):
        seconds = retry_after(str(exc)) or SPENT_REST
    else:
        seconds = REJECTED_REST
    _resting[key] = time.monotonic() + seconds
    print(f"  gemini key …{key[-4:]} resting {seconds / 60:.0f} min, {len(pool())} in the pool")


def _swap(ep: Endpoint, key: str) -> Endpoint:
    from .llm import _client  # noqa: PLC0415 - llm imports this module

    return ep._replace(client=_client(str(ep.client.base_url), key))


def _better(ep: Endpoint) -> Endpoint:
    """The same endpoint on a fresh key, if its own is resting and another is not."""
    own = ep.client.api_key
    if own not in pool() or _resting.get(own, 0) <= time.monotonic():
        return ep
    other = current()
    return _swap(ep, other) if other != own else ep


TRADED = (openai.RateLimitError, openai.AuthenticationError, openai.PermissionDeniedError)


async def rotating[T](ep: Endpoint, call: Callable[[Endpoint], Awaitable[T]]) -> T:
    """`call(ep)`, moving to the next key in the pool each time one is refused."""
    ep = _better(ep)
    tried: set[str] = set()
    while True:
        try:
            return await call(ep)
        except TRADED as exc:
            own = ep.client.api_key
            if own not in pool():  # LM Studio, or a key from before an edit
                raise
            rest(own, exc)
            tried.add(own)
            other = _better(ep)
            if other.client.api_key in tried:  # every key refused: the caller decides
                raise
            ep = other
