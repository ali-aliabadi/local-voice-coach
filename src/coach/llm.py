"""The model on the other side: Gemini, or a local model through LM Studio, both spoken
to through the OpenAI-compatible endpoint."""

import asyncio
import re
import time
from typing import NamedTuple

import openai
from openai import AsyncOpenAI

from . import config, settings
from .chunks import split_for_speech


class Reply(NamedTuple):
    """What a model said, and how long it made you wait for the first of it."""

    text: str
    ms: float | None


class Endpoint(NamedTuple):
    """Where a mode sends its requests. client, model and extra always travel together."""

    client: AsyncOpenAI
    model: str
    extra: dict


_clients: dict[tuple[str, str], AsyncOpenAI] = {}


def _client(base_url: str, api_key: str) -> AsyncOpenAI:
    """One client per server and key, kept. Each holds a connection pool: a new one per
    call paid a fresh TLS handshake every time, and left the old pool open."""
    # The SDK refuses to build a client without a key, which turned "no key set yet" into
    # a crash on every page that so much as asks which model the coach uses. Without one,
    # the request fails instead, and `explain` tells the user to add a key in Settings.
    key = (base_url, api_key or "no-key-set")
    if key not in _clients:
        _clients[key] = AsyncOpenAI(
            base_url=base_url, api_key=key[1], timeout=config.REQUEST_TIMEOUT
        )
    return _clients[key]


async def close() -> None:
    """Close every connection pool, as the server stops."""
    for client in _clients.values():
        await client.close()
    _clients.clear()


OPENING_NUDGE = "Begin."


def conversation(messages: list[dict]) -> list[dict]:
    """Make a message list every backend will accept.

    Gemini tolerates any ordering. Local models served through LM Studio render a jinja
    chat template that requires strict user/assistant alternation after the system
    message, and raises otherwise - which is what happens once the interviewer speaks
    first, or once a session is rebuilt from the database after a refresh.

    So: keep one system message, make sure the conversation opens on the candidate's
    side, and merge any two turns that ended up adjacent with the same role.
    """
    system = [m for m in messages if m["role"] == "system"][:1]
    rest = [dict(m) for m in messages if m["role"] != "system"]

    # The interviewer opening the conversation is normal here, but a chat template cannot
    # express it. Restore the instruction that produced it rather than dropping context.
    if rest and rest[0]["role"] != "user":
        rest.insert(0, {"role": "user", "content": OPENING_NUDGE})

    merged: list[dict] = []
    for message in rest:
        if merged and merged[-1]["role"] == message["role"]:
            merged[-1]["content"] += "\n\n" + message["content"]
        else:
            merged.append(message)
    return system + merged


def endpoint_for(backend, model_override: str | None = None) -> Endpoint:
    """Build the endpoint for a chosen backend. The only way endpoints are made.

    Credentials resolve here rather than in the catalogue, so editing the API key in the
    settings screen takes effect on the next session with no restart.
    """
    if backend.local:
        base_url, api_key = settings.get("lm_studio_url"), "lm-studio"
    else:
        base_url, api_key = config.BASE_URL, settings.api_key()
    return Endpoint(
        _client(base_url, api_key), model_override or backend.model, backend.extra or {}
    )


# Worth asking again: nothing came back, or the server broke. A rejected key is not.
RETRYABLE = (TimeoutError, openai.APIConnectionError, openai.InternalServerError)


async def _first_words(ep: Endpoint, messages, max_tokens):
    """Open a stream and wait for its first real token. Returns (stream, token)."""
    stream = await ep.client.chat.completions.create(
        model=ep.model,
        messages=conversation(messages),
        temperature=settings.get("temperature"),
        max_tokens=max_tokens or settings.get("reply_max_tokens"),
        stream=True,
        **ep.extra,
    )
    try:
        while True:
            chunk = await anext(stream)
            token = chunk.choices[0].delta.content if chunk.choices else ""
            if token:
                return stream, token
    except StopAsyncIteration:
        return stream, ""
    except BaseException:
        await stream.close()  # abandoned by the deadline: free the connection
        raise


async def stream_sentences(ep: Endpoint, messages, max_tokens=None, deadline=None):
    """Yield complete sentences as they arrive, so speech starts before generation ends.

    Yields ("sentence", str) for each chunk, then ("done", Reply) once.

    `deadline` is how long to wait for the first word before asking again, once. Nothing
    has been spoken at that point, so a retry cannot repeat anything. None waits as long
    as the client timeout allows - right for a reasoning model that thinks first.
    """
    started = time.perf_counter()
    for attempt in range(2):
        try:
            async with asyncio.timeout(deadline):
                stream, buffer = await _first_words(ep, messages, max_tokens)
            break
        except RETRYABLE:
            if attempt:
                raise
    # Measured from the first attempt: the wait the user actually sat through.
    first_ms = (time.perf_counter() - started) * 1000
    full = buffer
    spoke = False  # until the first chunk is out, a clause is enough
    async for chunk in stream:
        token = chunk.choices[0].delta.content if chunk.choices else ""
        if not token:
            continue
        buffer += token
        full += token
        speak, buffer = split_for_speech(buffer, eager=not spoke)
        if speak:
            spoke = True
            yield "sentence", speak
    speak, _ = split_for_speech(buffer, flush=True)
    if speak:
        yield "sentence", speak
    yield "done", Reply(full.strip(), first_ms)


async def complete(ep: Endpoint, messages, max_tokens=None) -> Reply:
    """One-shot, no streaming. For written output nobody is waiting to hear."""
    started = time.perf_counter()
    reply = await ep.client.chat.completions.create(
        model=ep.model,
        messages=conversation(messages),
        temperature=settings.get("temperature"),
        max_tokens=max_tokens or settings.get("review_max_tokens"),
        **ep.extra,
    )
    text = (reply.choices[0].message.content or "").strip()
    if not text:
        print(
            "⚠️  Empty reply — a thinking model likely spent the whole budget reasoning.\n"
            "   Raise 'Review max tokens' in Settings, or turn thinking off."
        )
    return Reply(text, (time.perf_counter() - started) * 1000)


# One background request at a time. Nobody is waiting on the coach or the study sheet, and
# free tiers count requests per minute: catching up a 23-answer session all at once got
# 20 of them refused.
_one_at_a_time = asyncio.Semaphore(1)
WAIT = re.compile(r"retry in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?")
# Past this it is a daily quota, not a per-minute one: waiting would hold up every other
# background request for hours. Gemini 3.8 Flash's free tier is 5 a minute and 20 a day.
LONGEST_WAIT = 120


def retry_after(message: str) -> float | None:
    """Seconds from "Please retry in 3h35m42.5s" or "retry in 33.8s"; None if not said."""
    found = WAIT.search(message)
    if not found or not any(found.groups()):
        return None
    hours, minutes, seconds = found.groups()
    return int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds or 0)


waiting = ""  # what the background queue is sitting out right now, for the page to say


async def patiently(ep: Endpoint, messages, max_tokens=None) -> Reply:
    """`complete`, one at a time, waiting out per-minute rate limits and an overloaded
    model ("high demand" is a 503, and passes); a daily quota that is used up fails at
    once, saying so."""
    global waiting
    async with _one_at_a_time:
        for _ in range(6):
            try:
                return await complete(ep, messages, max_tokens)
            except (openai.RateLimitError, openai.InternalServerError) as exc:
                wait = retry_after(str(exc)) or 30
                if wait > LONGEST_WAIT:
                    raise RuntimeError(
                        f"{ep.model} has used up its free requests for today; they come back "
                        f"in {wait / 3600:.1f} hours. Choose another model in Settings."
                    ) from None
                busy = "busy" if isinstance(exc, openai.InternalServerError) else "rate-limited"
                waiting = f"{ep.model} is {busy}, trying again in {wait:.0f}s"
                try:
                    await asyncio.sleep(wait + 1)
                finally:
                    waiting = ""
        return await complete(ep, messages, max_tokens)


async def explain(ep: Endpoint, exc: Exception) -> str:
    """Turn an exception into something the user can act on."""
    if isinstance(exc, TimeoutError | openai.APITimeoutError):
        return (
            f"{ep.model} did not start answering, even on a second try - it is probably "
            "overloaded. Nothing you said is lost: try again, or just carry on talking."
        )
    message = str(exc)
    if "404" in message or "not found" in message.lower():
        try:
            names = [m.id for m in (await ep.client.models.list()).data]
            usable = [n for n in names if "flash" in n or "pro" in n]
            return f"'{ep.model}' is not a valid model. Try: {', '.join(usable[:6])}"
        except Exception:
            pass
    if "api key" in message.lower() or "401" in message or "403" in message:
        return "That API key was rejected. Check it in Settings."
    return f"{ep.model}: {_said(exc)}"


def _said(exc: Exception) -> str:
    """The server's own words, not the SDK's "Error code: 400 - {'error': ...}" wrapper."""
    body = getattr(exc, "body", None)
    if isinstance(body, list) and body:  # Gemini wraps its error in a list
        body = body[0]
    error = body.get("error", body) if isinstance(body, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    return str(exc)
