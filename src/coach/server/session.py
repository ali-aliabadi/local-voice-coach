"""One WebSocket connection driving one practice session.

This is what a mode talks to. It replaces the microphone and the speaker with a socket,
and owns the two steps every mode repeats: hearing an answer and speaking a reply.
"""

import json
from typing import NamedTuple

import numpy as np

from .. import config, llm, settings, store, stt, tts

RECORDINGS = config.RECORDINGS


class SessionClosed(Exception):
    """The user finished, or the socket went away. Unwinds whatever mode is running."""


class Answer(NamedTuple):
    text: str
    metrics: dict | None


# What `answer()` returns when the user asked for the last reply again instead of speaking.
RETRY = "retry"


class BrowserIO:
    """Microphone in, speaker out, over one socket, for one session.

    Modes call `answer`, `reply`, `send` and `save_turn`. They never see the socket and
    never catch SessionClosed - the server does that around `mode.run`.
    """

    RETRY = RETRY

    def __init__(self, websocket, voice: tts.Voice, transcriber: stt.Transcriber, session: int):
        self.websocket = websocket
        self.voice = voice
        self.transcriber = transcriber
        self.session = session

    def prior_turns(self) -> list[dict]:
        """What was already said this session. Seed your history with it so that a browser
        refresh resumes the conversation rather than restarting it."""
        return store.conversation(self.session, limit=settings.get("history_turns") * 2)

    async def record(self) -> np.ndarray | str | None:
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
            elif message.get("text"):
                event = json.loads(message["text"])
                if event.get("type") == "quit":
                    raise SessionClosed
                if event.get("type") == "retry" and not chunks:
                    return RETRY
                if event.get("type") == "end_answer":
                    break
        if not chunks:
            return None
        audio = np.concatenate(chunks)
        if len(audio) < config.MIN_RECORD_SECONDS * config.SAMPLE_RATE:
            return None
        return audio

    async def answer(self) -> Answer | str | None:
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
        turn = self._save_answer(audio, text, metrics, stt_ms, words)
        await self.send(type="transcript", text=text, metrics=metrics, words=words, turn=turn)
        return Answer(text, metrics)

    async def reply(
        self,
        endpoint,
        messages: list[dict],
        role: str = "interviewer",
        cast: dict[str, str] | None = None,
        thinking: str | None = None,
    ) -> llm.Reply | None:
        """Speak the model's reply sentence by sentence, while it is still being written.

        `cast` maps speaker names to voices, for replies that open with "NAME:"; the turn
        is then saved as "role:NAME". Returns None if the model failed - the user has
        already been told, and offered a retry.
        """
        if thinking:
            await self.send(type="thinking", text=thinking)
        name, voice, done = None, None, llm.Reply("", None)
        try:
            async for kind, chunk in llm.stream_sentences(endpoint, messages):
                if kind == "done":
                    done = chunk
                    continue
                if cast and name is None:
                    name, chunk = llm.split_speaker(chunk, cast)
                    voice = cast.get(name)
                    if not chunk:
                        continue
                await self.send(type="sentence", text=chunk, speaker=name)
                await self.say(chunk, voice)
        except Exception as exc:
            await self.send(type="error", text=await llm.explain(endpoint, exc), retry=True)
            return None
        if done.text:
            self.save_turn(f"{role}:{name or '?'}" if cast else role, done.text, done.ms)
        await self.send(type="turn_done", latency_ms=done.ms)
        return done

    async def say(self, text: str, voice: str | None = None) -> None:
        """Synthesise and ship it. The browser queues playback; nothing plays here."""
        wav = await self.voice.wav(text, voice)
        await self.send(type="audio", bytes=len(wav))
        await self.websocket.send_bytes(wav)

    async def send(self, **payload) -> None:
        await self.websocket.send_text(json.dumps(payload))

    def save_turn(self, role: str, text: str, reply_ms: float | None = None) -> int | None:
        return store.record(self.session, role, text, reply_ms=reply_ms)

    def _save_answer(self, audio, text, metrics, stt_ms, words) -> int | None:
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
