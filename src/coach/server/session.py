"""One WebSocket connection driving one practice session.

This is what a mode talks to. It replaces the microphone and the speaker with a socket,
and owns the two steps every mode repeats: hearing an answer and speaking a reply.
"""

import json
import time
from typing import Any, Final, Literal, NamedTuple

import numpy as np
from starlette.websockets import WebSocket

from .. import chunks, coach, config, history, llm, settings, store, stt, tts

RECORDINGS = config.RECORDINGS


class SessionClosed(Exception):  # noqa: N818 - control flow, not an error
    """The user finished, or the socket went away. Unwinds whatever mode is running."""


class Answer(NamedTuple):
    text: str
    metrics: dict | None


# What `answer()` returns when the user asked for the last reply again instead of speaking.
RETRY: Final = "retry"
Retry = Literal["retry"]
# Accents a session can be given, so the ear is not trained on one voice. The better-rated
# Kokoro voices: American and British, women and men.
ACCENTS = (
    "af_heart", "bm_george", "am_michael", "bf_emma",
    "af_bella", "bm_fable", "am_puck", "bf_isabella",
)  # fmt: skip


class BrowserIO:
    """Microphone in, speaker out, over one socket, for one session.

    Modes call `answer`, `reply`, `send` and `save_turn`. They never see the socket and
    never catch SessionClosed - the server does that around `mode.run`.
    """

    RETRY: Final = RETRY

    def __init__(
        self, websocket: WebSocket, voice: tts.Voice, transcriber: stt.Transcriber, session: int
    ) -> None:
        self.websocket = websocket
        self.voice = voice
        self.transcriber = transcriber
        self.session = session
        # The same accent for the whole session, and again after a reload.
        on = settings.get("vary_voice") == "on"
        self.accent = ACCENTS[session % len(ACCENTS)] if on else None
        self.last_reply: tuple[str, str | None] = ("", None)  # for "say it slower"
        self.last_turn: int | None = None  # the reply the user is answering
        self.heard_at: float | None = None  # when the user finished their last answer

    def prior_turns(self) -> list[dict]:
        """What was already said this session. Seed your history with it so that a browser
        refresh resumes the conversation rather than restarting it."""
        return store.conversation(self.session, limit=settings.get("history_turns") * 2)

    async def record(self) -> np.ndarray | Retry | None:
        """Gather raw PCM frames until the client says the answer is finished.

        The browser sends Float32 at 16kHz - exactly what Whisper wants - so there is no
        decoding here and no ffmpeg anywhere in the project.
        """
        chunks: list[np.ndarray] = []
        while True:
            message = await self.websocket.receive()
            if message["type"] == "websocket.disconnect":
                raise SessionClosed
            if message.get("bytes"):
                chunks.append(np.frombuffer(message["bytes"], dtype=np.float32))
                continue
            kind = await self._event(json.loads(message["text"])) if message.get("text") else None
            if kind == "retry" and not chunks:
                return RETRY
            if kind == "end_answer":
                break
        if not chunks:
            return None
        audio = np.concatenate(chunks)
        if len(audio) < config.MIN_RECORD_SECONDS * config.SAMPLE_RATE:
            return None
        return audio

    async def _event(self, event: dict) -> str | None:
        """Act on one thing the page said while an answer is being recorded; return its type."""
        kind = event.get("type")
        if kind == "quit":
            raise SessionClosed
        if kind == "slower":
            await self._slower()
        if kind == "helped" and self.last_turn:
            store.helped(self.last_turn, [str(k) for k in event.get("kinds", [])][:3])
        if kind == "end_answer":
            self.heard_at = time.perf_counter()
        return kind

    async def answer(self) -> Answer | Retry | None:
        """Hear one answer: record it, transcribe it, score it, save it, show it.

        Returns the Answer, RETRY if the user asked to hear the last reply again, or None
        when nothing usable came in (the user has already been told why).
        """
        audio = await self.record()
        if audio is None:
            await self.send(type="notice", text="Nothing recorded - hold it a little longer.")
            return None
        if isinstance(audio, str):
            return audio
        text, metrics, words, stt_ms = await self.transcriber.transcribe(audio)
        if not text:
            await self.send(type="notice", text="Didn't catch that. Move closer to the mic.")
            return None
        asked = store.last_said(self.session)
        turn = self._save_answer(audio, text, metrics, stt_ms, words)
        coach.note(self.session, turn, asked, text)  # in the background, never waited on
        await self.send(
            type="transcript",
            text=text,
            metrics=history.rates(metrics) if metrics else None,
            words=words,
            turn=turn,
            session=history.so_far(self.session),
        )
        return Answer(text, metrics)

    async def reply(
        self,
        endpoint: llm.Endpoint,
        messages: list[dict],
        *,
        role: str = "interviewer",
        cast: dict[str, str] | None = None,
        thinking: str | None = None,
        deadline: float | None = None,
        max_tokens: int | None = None,
    ) -> llm.Reply | None:
        """Speak the model's reply sentence by sentence, while it is still being written.

        `cast` maps speaker names to voices, for replies that open with "NAME:"; the turn
        is then saved as "role:NAME". `deadline` is how long to wait for the first word
        before asking again (see llm.stream_sentences). Returns None if the model failed -
        the user has already been told, and offered a retry.
        """
        if thinking:
            await self.send(type="thinking", text=thinking)
        name, voice, done = None, self.accent, llm.Reply("", None)
        began, first, heard = time.perf_counter(), None, None
        try:
            async for kind, chunk in llm.stream_sentences(
                endpoint, messages, max_tokens=max_tokens, deadline=deadline
            ):
                if kind == "done":
                    done = chunk
                    continue
                if cast and name is None:
                    name, rest = chunks.split_speaker(chunk, cast)
                    voice = cast.get(name) if name else None
                    if not rest:
                        continue
                    chunk = rest  # noqa: PLW2901 - the same sentence, its speaker taken off
                first = first or time.perf_counter()
                await self.send(type="sentence", text=chunk, speaker=name)
                await self.say(chunk, voice)
                heard = heard or time.perf_counter()
        except Exception as exc:
            self.heard_at = None  # a wait that ended in an error is not a reply time
            await self.send(type="error", text=await llm.explain(endpoint, exc), retry=True)
            return None
        timing = self._timing(began, first, heard)
        if done.text:
            self.last_turn = store.record(
                self.session,
                f"{role}:{name or '?'}" if cast else role,
                done.text,
                reply_ms=done.ms,
                timing=timing,
            )
            spoken = chunks.split_speaker(done.text, cast)[1] if cast else done.text
            self.last_reply = (spoken, voice)
        await self.send(type="turn_done", latency_ms=done.ms, wait_ms=(timing or {}).get("total"))
        return done

    def _timing(self, began: float, first: float | None, heard: float | None) -> dict | None:
        """Where the wait went, from the end of your answer to the first sound back:
        hearing you (transcription), thinking (the model's first chunk), voicing (Kokoro).
        Measured on every reply, because a published latency is not your latency."""
        if first is None or heard is None:
            return None
        ms = lambda a, b: round((b - a) * 1000)  # noqa: E731
        timing = {"thinking": ms(began, first), "voicing": ms(first, heard)}
        if self.heard_at is not None:
            timing |= {"hearing": ms(self.heard_at, began), "total": ms(self.heard_at, heard)}
        self.heard_at = None
        return timing

    async def speak(self, text: str) -> None:
        """Say a fixed line as the partner - no model. For modes that run to a script."""
        await self.send(type="sentence", text=text)
        await self.say(text, self.accent)
        self.last_turn = self.save_turn("interviewer", text)
        self.last_reply = (text, self.accent)
        await self.send(type="turn_done")

    async def _slower(self) -> None:
        """The last reply again, slower. Marked as a replay, so "again" keeps the original."""
        text, voice = self.last_reply
        if text:
            wav = await self.voice.wav(text, voice, slower=True)
            await self.send(type="audio", bytes=len(wav), replay=True)
            await self.websocket.send_bytes(wav)

    async def say(self, text: str, voice: str | None = None) -> None:
        """Synthesise and ship it. The browser queues playback; nothing plays here."""
        wav = await self.voice.wav(text, voice)
        await self.send(type="audio", bytes=len(wav))
        await self.websocket.send_bytes(wav)

    async def send(self, **payload: Any) -> None:
        await self.websocket.send_text(json.dumps(payload))

    def save_turn(self, role: str, text: str, reply_ms: float | None = None) -> int:
        return store.record(self.session, role, text, reply_ms=reply_ms)

    def _save_answer(
        self, audio: np.ndarray, text: str, metrics: dict | None, stt_ms: float, words: list[dict]
    ) -> int:
        """Persist the answer and its recording. Returns the turn id for playback."""
        folder = RECORDINGS / str(self.session)
        folder.mkdir(parents=True, exist_ok=True)
        count = len(list(folder.glob("*.wav")))
        destination = folder / f"{count:03d}.wav"
        destination.write_bytes(tts.encode_wav(audio, config.SAMPLE_RATE))
        return store.record(
            self.session,
            "you",
            text,
            metrics,
            stt_ms=stt_ms,
            audio_path=str(destination),
            word_rows=words,
        )
