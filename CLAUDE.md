# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Project Overview

Spoken software-engineering interview practice. The user answers out loud, a model plays
the interviewer, and every answer is scored for fluency so hesitation can be tracked over
time. Intended to be published for others to use and contribute to.

The goal behind every design choice: the user wants to cut filler words ("mmmm") and
shorten the time it takes to form a sentence under interview pressure. They practise about
an hour a day.

## Architecture

```
main.py  --mode {talk,panel,review}
   │
   ├── Whisper (local) ──► word timestamps ──► fluency()  wpm · fillers · pauses · lead-in
   │                                              arithmetic only, no model, no network
   ├── Gemini / local LLM (cloud or localhost) ──► the interviewer
   └── Kokoro (local, 54 voices) ──────────────► the voice(s)
                                │
                                ▼
                  english_practice_log.md   per-answer scores + session averages
```

Only transcript **text** reaches the model. Audio never leaves the machine.

## Commands

```bash
uv pip install -e .
echo 'GEMINI_API_KEY=...' > .env     # gitignored, read by config.load_env()
python main.py [--mode talk|panel|review] [--backend ...] [--stats]
./scripts/check.sh                   # ruff + format + line budget + tests
```

`python` may not be on PATH — use `./.venv/bin/python`.

## Layout

| Path | Holds |
|---|---|
| `src/coach/config.py` | every tunable. Contributors look here first. |
| `src/coach/audio.py` | keypress, recording, the `Speaker` playback worker |
| `src/coach/stt.py` | `Transcriber` and `fluency()` |
| `src/coach/llm.py` | `Endpoint`, streaming, sentence chunking, error hints |
| `src/coach/backends.py` | the backend catalogue, plus internet/LM-Studio probing |
| `src/coach/picker.py` | the startup tree (mode, then backend) |
| `src/coach/store.py` | SQLite: sessions, turns, measured latency |
| `src/coach/session.py` | the end-of-session scoreboard and `--stats` trend |
| `src/coach/modes/` | one file per mode, discovered automatically |

## House rules

- **One code file at the repo root**: `main.py`. Everything else lives in `src/coach/`,
  `tests/` or `scripts/`.
- **300 lines per file, hard cap**, warned at 240, enforced by `scripts/check_lines.py`.
  An agent pays for every line twice — reading it and reasoning about it. When a file
  crosses, split along a real seam; two tangled files are worse than one coherent one.
- **`ruff` is the standard**, configured in `pyproject.toml`. `./scripts/check.sh` runs
  everything CI would. `# fmt: off` only for data tables where alignment carries meaning.
- Full detail in [CONTRIBUTING.md](CONTRIBUTING.md).

## The mode contract

**Adding a mode must never require editing another file.** Modes are discovered with
`pkgutil` in `src/coach/modes/__init__.py`. A mode declares `HELP`, `ENDPOINT` (`"fast"` or
`"deep"`), and `async def run(endpoint, transcriber, speaker) -> list[dict]`.

Do not reintroduce a branch on mode name in `main.py`. If a mode needs a different
backend, add an entry to `llm.ENDPOINTS`, not an `if`.

## Key decisions

### Fluency metrics are arithmetic, not a model
`fluency()` counts words and measures gaps between timestamps. Deliberately not an LLM
call: counting is exact, free, offline and instant. Do not replace it.
`PAUSE_SECONDS` (0.6) is a calibration knob, not a magic number.

### Whisper deletes the thing being measured
Whisper is trained to tidy speech up and silently drops "um"/"uh".
`initial_prompt=DISFLUENCY_HINT` biases it back toward verbatim, so filler counts are a
floor, not a census. `word_timestamps=True` is load-bearing. CrisperWhisper is the proper
fix if exact filler counts ever matter.

### Thinking models and `max_tokens`
`gemini-3.8-flash` spends `max_tokens` on hidden reasoning and returns fragments like
`"Length: 1"` unless it is switched off; Flash-Lite **rejects** `reasoning_effort` outright.
So the flag travels with the model in `config.*_EXTRA`, never set globally.

### Backends are data, not branches
`backends.CATALOGUE` is the single list of everything that can play the interviewer. A mode
declares a role (`"fast"`/`"deep"`); `survey()` filters the catalogue to that role and marks
each row reachable or not. Adding a model is one row. Never branch on backend key.

### Latency shown to the user must be honest
The `Latency` column is published/estimated and labelled `est.` where it is a guess. The
`Yours` column is `AVG(reply_ms)` from the user's own sessions in SQLite. Measured numbers
beat published ones; do not present an estimate as a measurement.

### Local reasoning models need a large token budget
Bonsai-27B returned an **empty** reply at `max_tokens=500` — thinking consumed the whole
budget, exactly like `gemini-3.8-flash` did at 120. `REVIEW_MAX_TOKENS` is 2500, and
`llm.complete` prints an explanation on an empty reply rather than failing silently.

### Model choices
- `FAST_MODEL` pinned to `gemini-3.5-flash-lite` (~1.1s first token, ~$0.42/mo at 1h/day).
  `gemini-flash-lite-latest` resolves to the same model; pinned wins because an alias can
  roll to different quota mid-habit.
- Local backends are reached through LM Studio's OpenAI-compatible server on :1234.
  `MODE=` and `BACKEND=` in `.env` skip the startup prompts.
- Client `timeout=20.0`: one test request hung 51s. The SDK retries twice by default.

## Conventions

- Constants, not config objects. A frozen dataclass instantiated once was removed as ceremony.
- Non-trivial logic gets one assert in `tests/test_coach.py`. No frameworks, no fixtures.
- `ponytail:` comments mark deliberate shortcuts and name the upgrade path.

## Rejected alternatives (don't re-propose without new information)

| Option | Why not |
|---|---|
| Bigger local model for conversation | 18GB M3 Pro: 4B makes errors, 9B too slow. Local models are offered for `review`, and as an offline fallback for `talk`. |
| Vision-language models (GLM-4.6V Flash) | Nothing in this app looks at images. |
| Speech-to-speech (Gemini Live) | ~$17/mo and a 15-min session cap = 4+ reconnects in an hour. |
| Cloud TTS (Seed Audio, Gemini TTS) | $6–67/mo to replace Kokoro, which is free and already good. |
| `interview-coach-llama3-8b` style fine-tunes | Undocumented hobby LoRAs on a 2024 base. Fine-tuning teaches style, not knowledge. |
| JEV / structured-decision models | Can't hold a conversation; the scoring it would do is arithmetic. |
| LLM-based fluency scoring | Timestamps are exact and free. |
