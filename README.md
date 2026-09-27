# local-voice-coach

Offline English conversation practice. Push-to-talk speech in, spoken reply out:
Whisper (STT) → a local LLM via LM Studio → Kokoro (TTS). Nothing leaves the machine.

## Setup

```bash
uv pip install -e .
```

Download `kokoro-v1.0.onnx` and `voices-v1.0.bin` into the repo root
(https://github.com/thewh1teagle/kokoro-onnx releases), and start LM Studio on
`localhost:1234` serving the model named in `LLM_MODEL` in `main.py`.

## Run

```bash
python main.py
```

Any key starts recording, any key stops it, `q` quits. Turns are appended to
`english_practice_log.md`. All config is the constants at the top of `main.py`.

## Test

```bash
python test_main.py
```
