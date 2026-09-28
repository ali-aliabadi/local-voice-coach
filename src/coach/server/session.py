"""One WebSocket connection driving one practice session.

This is what a mode talks to. It replaces the microphone and the speaker with a socket,
which is the only reason modes needed changing at all.
"""

import json
import pathlib

import numpy as np

from .. import config, store, tts

RECORDINGS = pathlib.Path("recordings")


class SessionClosed(Exception):
    """The user finished, or the socket went away. Unwinds whatever mode is running."""


class BrowserIO:
    """Microphone in, speaker out, over one socket.

    Modes call `record`, `say`, `send` and `save_answer`. They never see the socket and
    never catch SessionClosed - the server does that around `mode.run`.
    """

    def __init__(self, websocket, voice: tts.Voice) -> None:
        self.websocket = websocket
        self.voice = voice

    def prior_turns(self) -> list[dict]:
        """What was already said this session. Seed your history with it so that a browser
        refresh resumes the conversation rather than restarting it."""
        return store.conversation()

    async def record(self) -> np.ndarray | None:
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
                if event.get("type") == "end_answer":
                    break
        if not chunks:
            return None
        audio = np.concatenate(chunks)
        if len(audio) < config.MIN_RECORD_SECONDS * config.SAMPLE_RATE:
            return None
        return audio

    async def say(self, text: str, voice: str | None = None) -> None:
        """Synthesise and ship it. The browser queues playback; nothing plays here."""
        wav = await self.voice.wav(text, voice)
        await self.send(type="audio", bytes=len(wav))
        await self.websocket.send_bytes(wav)

    async def send(self, **payload) -> None:
        await self.websocket.send_text(json.dumps(payload))

    async def drain(self) -> None:
        """No-op by design.

        In the terminal this stopped us recording over the interviewer's voice. Here the
        browser owns the microphone and keeps it shut until playback ends, and `record`
        blocks on the client regardless - so there is nothing to wait for.
        """

    def save_answer(
        self, audio: np.ndarray, text: str, metrics: dict | None, stt_ms: float
    ) -> int | None:
        """Persist the answer and its recording. Returns the turn id for playback."""
        session_id = store.current_session()
        path = None
        if session_id is not None:
            folder = RECORDINGS / str(session_id)
            folder.mkdir(parents=True, exist_ok=True)
            count = len(list(folder.glob("*.wav")))
            destination = folder / f"{count:03d}.wav"
            destination.write_bytes(tts.encode_wav(audio, config.SAMPLE_RATE))
            path = str(destination)
        return store.record("you", text, metrics, stt_ms=stt_ms, audio_path=path)
