"""Spoken software-engineering interview practice.

Local ears and voice (Whisper + Kokoro); the interviewer runs in the cloud or locally.
Run it with no arguments and it asks which mode and which backend. Pass --mode/--backend
(or set MODE=/BACKEND= in .env) to skip the prompts.

Modes live in coach/modes/ and register themselves - see that package's docstring.
"""

import argparse
import asyncio
import sys

import sounddevice as sd
from kokoro_onnx import Kokoro

from coach import backends, config, llm, picker, session, store
from coach.audio import Speaker
from coach.modes import discover
from coach.stt import Transcriber

MODES = discover()


async def main(name: str, backend, endpoint) -> None:
    mode = MODES[name]
    where = "local" if backend.local else "cloud"
    store.start(name, backend.key, endpoint.model)

    print("\n⏳ Loading Whisper (STT)...")
    transcriber = Transcriber()
    print("⏳ Loading Kokoro (TTS)...")
    speaker = Speaker(Kokoro(config.TTS_MODEL_PATH, config.TTS_VOICES_PATH))
    print(f"✅ Ready. {name} · {endpoint.model} ({where})")

    try:
        await mode.run(endpoint, transcriber, speaker)
        print("\nSession over. Nice work.")
    finally:
        store.finish()
        session.print_summary(name)
        await speaker.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--mode",
        choices=sorted(MODES),
        help="  ".join(f"{n}: {m.HELP}" for n, m in sorted(MODES.items())),
    )
    parser.add_argument(
        "--backend",
        choices=sorted(backends.BY_KEY),
        help="skip the interviewer prompt and use this backend",
    )
    parser.add_argument("--model", help="override the model on the chosen backend")
    parser.add_argument(
        "--stats", action="store_true", help="print your progress across past sessions and exit"
    )
    args = parser.parse_args()

    if args.stats:
        session.print_trend()
        raise SystemExit

    # Push-to-talk reads raw keypresses, which needs a real terminal.
    if not sys.stdin.isatty():
        raise SystemExit(
            "Run this from a terminal - push-to-talk needs a tty.\n  ./.venv/bin/python main.py"
        )

    mode_name = args.mode or config.DEFAULT_MODE or picker.choose_mode(MODES)
    role = MODES[mode_name].ENDPOINT
    key = args.backend or config.DEFAULT_BACKEND
    backend = backends.BY_KEY[key] if key else picker.choose_backend(role, mode_name)

    try:
        asyncio.run(main(mode_name, backend, llm.endpoint_for(backend, args.model)))
    except KeyboardInterrupt:
        sd.stop()
        print("\nSession ended.")
