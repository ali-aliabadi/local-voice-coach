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


OPENING_NUDGE = "Begin the interview."


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


# A sentence ends at .!?… when the next thing is whitespace or the end of the buffer.
# "3.5" never matches, because the dot there is followed by a digit.
TERMINATOR = re.compile(r"[.!?…]+[\"')\]]*(?=\s|$)")
ABBREVIATION = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|St|vs|etc|e\.g|i\.e|No|Inc|Ltd|Jr|Sr)\.$")


def _boundaries(text: str):
    """Offsets where a sentence genuinely ends. Abbreviations are not endings."""
    settled = len(text.rstrip())
    for match in TERMINATOR.finditer(text):
        head = text[: match.end()]
        if ABBREVIATION.search(head):
            continue
        # A trailing "3." may still become "3.5" once the next token lands.
        if match.end() >= settled and len(head) >= 2 and head[-1] == "." and head[-2].isdigit():
            continue
        yield match.end()


def split_for_speech(buffer: str, flush: bool = False) -> tuple[str, str]:
    """Split the buffer into (speak now, keep buffering).

    Splits at the LAST complete sentence inside the buffer, rather than only when the
    buffer happens to end on one. Models stream several words per token, so a boundary
    usually lands in the middle of a token ("own. Walk me"). A check that only looked at
    the tail missed it, the buffer kept growing, and the length cap eventually cut a
    sentence in half - which is why the interviewer stopped mid-sentence.

    The returned buffer is never stripped: the trailing space is what keeps the next
    token from being glued onto the last word.
    """
    if flush:
        return buffer.strip(), ""
    if not buffer.strip():
        return "", buffer

    cuts = list(_boundaries(buffer))
    if cuts:
        return buffer[: cuts[-1]].strip(), buffer[cuts[-1] :].lstrip()

    # Nothing has ended yet. Only give up waiting once this has run on far too long, and
    # then break between words - never inside one.
    if len(buffer.strip()) >= config.MAX_CHARS_BEFORE_FLUSH:
        space = buffer.rstrip().rfind(" ")
        if space > 0:
            return buffer[:space].strip(), buffer[space:].lstrip()
    return "", buffer


async def stream_sentences(ep: Endpoint, messages, max_tokens=None):
    """Yield complete sentences as they arrive, so speech starts before generation ends.

    Yields ("sentence", str) for each chunk, then ("done", Reply) once.
    """
    started = time.perf_counter()
    first_ms = None
    stream = await ep.client.chat.completions.create(
        model=ep.model,
        messages=conversation(messages),
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
        speak, buffer = split_for_speech(buffer)
        if speak:
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
