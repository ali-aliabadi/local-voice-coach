"""End to end over a real socket. Run: python tests/test_wire.py  (or `make e2e`)

The real server, a real WebSocket client, a spoken answer synthesised by Kokoro, and a
fake OpenAI-compatible model that records what it was sent. Starlette's TestClient fakes
the socket in-process and once passed while the real app could not connect at all.

Needs the Kokoro weights (`make models`) and loads Whisper, so it is not in check.sh.
"""

import asyncio
import json
import os
import pathlib
import socket
import sqlite3
import sys
import tempfile
import threading
import time

from coach import config  # noqa: I001

data = pathlib.Path(tempfile.mkdtemp())
config.DB_PATH = str(data / "wire.db")
config.RECORDINGS = data / "recordings"
config.FIRST_WORD_SECONDS = 1.0  # so a hung model is abandoned in a second, not twenty
if not pathlib.Path(config.TTS_MODEL_PATH).exists():
    print("skipped: no Kokoro weights - run `make models`")
    sys.exit(0)

import numpy as np  # noqa: E402
import uvicorn  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.responses import JSONResponse, StreamingResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from websockets.asyncio.client import connect  # noqa: E402

from coach import tts  # noqa: E402
from coach.server.app import app  # noqa: E402

# ---- a fake model: each request pops the next scripted reply; "HANG" never answers ----
script: list[str] = []
received: list[list[dict]] = []


NOTES = {"fixes": [{"said": "I watched", "better": "we watched", "why": "x", "kind": "tense"}]}
SUMMARY = {"recap": "They talked about films.", "work_on": ["tenses"], "went_well": "clear"}


async def completions(request):
    body = await request.json()
    system = body["messages"][0]["content"]
    if "English coach" in system:  # the coach, in the background: answer it at once
        canned = SUMMARY if "session summary" in system else NOTES
        return JSONResponse(
            {
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(canned)},
                        "finish_reason": "stop",
                    }
                ]
            }
        )
    received.append(body["messages"])
    text = script.pop(0)

    async def events():
        if text == "HANG":
            await asyncio.sleep(3600)
        for word in text.split(" "):
            chunk = {"choices": [{"index": 0, "delta": {"content": word + " "}}]}
            yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


fake = Starlette(
    routes=[
        Route("/v1/chat/completions", completions, methods=["POST"]),
        Route("/v1/models", lambda _r: JSONResponse({"data": []})),
    ]
)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(application, port: int) -> None:
    server = uvicorn.Server(uvicorn.Config(application, port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        assert thread.is_alive(), "server failed to start"
        time.sleep(0.1)


# The database belongs to the server's thread (sqlite refuses to share a connection), so
# the fake model is wired in through the environment, not settings.set().
fake_port, app_port = free_port(), free_port()
os.environ["LM_STUDIO_URL"] = f"http://127.0.0.1:{fake_port}/v1"
os.environ["COACH_BACKEND"] = "gemma4-e4b"  # a local model, so the coach uses the fake too
serve(fake, fake_port)
serve(app, app_port)  # loads Whisper and Kokoro before it reports started


def speech(text: str) -> bytes:
    """A spoken answer, as the browser would send it: Float32 PCM at 16kHz."""
    samples, rate = tts.Voice().kokoro.create(text, voice="am_puck", speed=1.0)
    positions = np.arange(0, len(samples), rate / config.SAMPLE_RATE)
    pcm = np.interp(positions, np.arange(len(samples)), samples).astype(np.float32)
    return np.concatenate([np.zeros(8000, np.float32), pcm]).tobytes()  # 0.5s lead-in


async def until(ws, kind: str) -> dict:
    """Read events until one of `kind` arrives; audio frames are skipped."""
    while True:
        message = await asyncio.wait_for(ws.recv(), timeout=60)
        if isinstance(message, str) and json.loads(message)["type"] == kind:
            return json.loads(message)


async def speak(ws, text: str) -> dict:
    await ws.send(speech(text))
    await ws.send(json.dumps({"type": "end_answer"}))
    return await until(ws, "transcript")


async def main() -> None:
    script.extend(["Hi there. What did you do this weekend?", "Oh nice. Which film was it?"])
    script.extend(["HANG", "HANG", "Sorry, I lost you. Was it scary?"])
    async with connect(f"ws://127.0.0.1:{app_port}/ws") as ws:
        await ws.send(json.dumps({"mode": "talk", "backend": "lfm2.5"}))
        session = (await until(ws, "ready"))["session"]
        assert (await until(ws, "sentence"))["text"] == "Hi there."  # the partner opens
        await until(ws, "turn_done")

        heard = await speak(ws, "I watched a film at home with my wife.")
        assert "film" in heard["text"].lower(), heard["text"]
        assert heard["metrics"]["wpm"] > 0 and heard["turn"]
        await until(ws, "turn_done")

        # the model hangs twice: one silent retry, then a visible error offering another
        await speak(ws, "It was Seven, the old one with Brad Pitt.")
        failed = await until(ws, "error")
        assert failed["retry"] and "try again" in failed["text"], failed
        await ws.send(json.dumps({"type": "retry"}))  # re-ask without speaking again
        assert (await until(ws, "sentence"))["text"] == "Sorry, I lost you."
        await until(ws, "turn_done")

    # the model was sent the whole conversation, not just the last answer
    second = received[1]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"], second
    assert "film" in second[-1]["content"].lower()
    # and the answer that got no reply was kept for the retry, not dropped
    retried = received[-1]
    assert len(retried) == 6 and "brad pitt" in retried[-1]["content"].lower(), retried
    saved = sqlite3.connect(config.DB_PATH).execute(
        "SELECT role FROM turns WHERE session_id = ? ORDER BY id", (session,)
    )
    roles = [row[0] for row in saved]
    assert roles == ["interviewer", "you", "interviewer", "you", "interviewer"], roles

    # the coach wrote notes on both answers in the background, then summarised on close
    for _ in range(50):
        db = sqlite3.connect(config.DB_PATH)
        notes = db.execute(
            "SELECT notes FROM turns WHERE session_id = ? AND role = 'you'", (session,)
        ).fetchall()
        summary = db.execute("SELECT summary FROM sessions WHERE id = ?", (session,)).fetchone()
        if all(n[0] for n in notes) and summary[0]:
            break
        await asyncio.sleep(0.2)
    assert all(json.loads(n[0]) == NOTES for n in notes), notes
    assert (
        json.loads(summary[0])["recap"] == SUMMARY["recap"]
        and json.loads(summary[0])["answers"] == 2
    )


asyncio.run(main())
print("ok")
