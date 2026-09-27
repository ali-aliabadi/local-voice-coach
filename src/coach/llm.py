"""The cloud interviewer. Gemini, spoken to through the OpenAI-compatible endpoint."""

import re
import time
from typing import NamedTuple

from openai import AsyncOpenAI

from . import config, settings

TERMINATORS = (".", "!", "?", "…")
ABBREVIATIONS = re.compile(r"\b(Mr|Mrs|Ms|Dr|St|vs|etc|e\.g|i\.e)\.$")


class Reply(NamedTuple):
    """What a model said, and how long it made you wait for the first of it."""

    text: str
    ms: float | None


class Endpoint(NamedTuple):
    """Where a mode sends its requests. client, model and extra always travel together."""

    client: AsyncOpenAI
    model: str
    extra: dict


def _client(base_url: str, api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=config.REQUEST_TIMEOUT)


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


def ready_to_speak(buffer: str) -> bool:
    """True once the buffer holds something worth sending to the speaker."""
    # ponytail: naive sentence heuristic; swap in a real segmenter if it mis-splits
    text = buffer.strip()
    if len(text) < 3:
        return False
    if "\n" in buffer or len(text) >= config.MAX_CHARS_BEFORE_FLUSH:
        return True
    if not text.endswith(TERMINATORS):
        return False
    if text.endswith(".") and text[-2].isdigit():  # "3.5"
        return False
    return not ABBREVIATIONS.search(text)


async def stream_sentences(ep: Endpoint, messages, max_tokens=None):
    """Yield complete sentences as they arrive, so speech starts before generation ends.

    Yields ("sentence", str) for each chunk, then ("done", Reply) once.
    """
    started = time.perf_counter()
    first_ms = None
    stream = await ep.client.chat.completions.create(
        model=ep.model,
        messages=messages,
        temperature=settings.get("temperature"),
        max_tokens=max_tokens or settings.get("reply_max_tokens"),
        stream=True,
        **ep.extra,
    )
    buffer, full = "", ""
    async for chunk in stream:
        if not chunk.choices:
            continue
        token = chunk.choices[0].delta.content or ""
        if not token:
            continue
        if first_ms is None:
            first_ms = (time.perf_counter() - started) * 1000
        buffer += token
        full += token
        if ready_to_speak(buffer):
            if buffer.strip():
                yield "sentence", buffer.strip()
            buffer = ""
    if buffer.strip():
        yield "sentence", buffer.strip()
    yield "done", Reply(full.strip(), first_ms)


async def complete(ep: Endpoint, messages, max_tokens=None) -> Reply:
    """One-shot, no streaming. For written output nobody is waiting to hear."""
    started = time.perf_counter()
    reply = await ep.client.chat.completions.create(
        model=ep.model,
        messages=messages,
        temperature=settings.get("temperature"),
        max_tokens=max_tokens or settings.get("review_max_tokens"),
        **ep.extra,
    )
    text = (reply.choices[0].message.content or "").strip()
    if not text:
        print(
            "⚠️  Empty reply — a thinking model likely spent the whole budget reasoning.\n"
            "   Raise REVIEW_MAX_TOKENS in coach/config.py, or turn thinking off."
        )
    return Reply(text, (time.perf_counter() - started) * 1000)


async def explain(ep: Endpoint, exc: Exception) -> str:
    """Turn an exception into something the user can act on."""
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
    return message
