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

The browser is an I/O device. Everything that thinks runs in Python. Full reasoning in
[DESIGN.md](DESIGN.md) — read it before proposing a structural change.

```
browser                          server (localhost)
AudioWorklet ──raw PCM 16kHz───► Whisper ──► fluency()   arithmetic, no model
                                     │
                                     ▼   Gemini, or LM Studio
  audio player ◄────WAV frames──── Kokoro
  transcript / timeline / charts ◄─ JSON events over one WebSocket
                                     │
                                 SQLite + recordings/
```

## Commands

```bash
make install                         # dependencies
make models                          # Kokoro weights into models/ (~340MB, once)
make run                             # native, serves http://127.0.0.1:8000
make up / down / logs                # the same thing in Docker
make check                           # ruff + format + line budget + tests
```

`make` with no target lists everything. `python` may not be on PATH — use
`./.venv/bin/python`.

## Layout

| Path | Holds |
|---|---|
| `main.py` | the only root module: argument parsing, starts uvicorn |
| `src/coach/config.py` | constants that are not user-facing |
| `src/coach/settings.py` | user-editable settings; SPEC drives the settings UI |
| `src/coach/stt.py` | Whisper, `fluency()`, `word_rows()` |
| `src/coach/tts.py` | Kokoro to WAV bytes; touches no audio device |
| `src/coach/llm.py` | endpoints, streaming, sentence chunking |
| `src/coach/backends.py` | the model catalogue and reachability probing |
| `src/coach/store.py` | SQLite: writing sessions, turns, settings, retention |
| `src/coach/history.py` | reading it back: one session, all sessions, totals |
| `src/coach/profile.py` | who the candidate is, and the system prompt built from it |
| `src/coach/server/` | `app.py` assembly + websocket, `api.py` JSON routes, `models.py` loaded models |
| `src/coach/modes/` | one file per mode, discovered automatically |
| `web/` | plain ES modules, no build step; `views/` is one file per route |
| `models/` | Kokoro weights, gitignored, fetched by `make models` |
| `data/` | sessions, metrics, recordings — gitignored, mounted as a volume |

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
`pkgutil` in `src/coach/modes/__init__.py`. A mode declares `HELP`, `ENDPOINT` (`"fast"`
or `"deep"`), and `async def run(endpoint, transcriber, io)`.

`io` is the browser: `await io.record()`, `await io.say(text, voice)`,
`await io.send(**event)`, `io.save_answer(...)`, and `io.prior_turns()` to resume a
session after a refresh. Modes loop forever and never catch `SessionClosed` — the server
catches it when the user stops.

Do not reintroduce a branch on mode name. A mode needing a different backend names a role
in `ENDPOINT`; `backends.CATALOGUE` does the rest.

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
So the flag travels with the model in the catalogue's `extra`, never set globally.

### Messages must alternate, for local models
LM Studio renders a jinja chat template that requires strict user/assistant alternation
after the system message and raises `"roles must alternate"` otherwise. Gemini tolerates
anything, so this only shows up on a local backend — it broke as soon as the interviewer
started speaking first. `llm.conversation()` normalises every outgoing message list at the
single choke point; do not bypass it by calling `client.chat.completions.create` directly.

### Sentence splitting must search the buffer, not just its tail
Models stream several words per token, so a sentence boundary usually arrives in the
middle of a token (`"own. Walk me"`). The old `ready_to_speak` only asked whether the
buffer *ended* on a terminator, missed those boundaries entirely, and then
`MAX_CHARS_BEFORE_FLUSH` cut sentences in half — the interviewer audibly stopped
mid-sentence and it read as bad text-to-speech. `llm.split_for_speech` finds the last
real boundary inside the buffer instead.

Two traps it has to avoid: the returned buffer must **not** be stripped, or the trailing
space disappears and the next token glues onto the last word (`"wordword"`); and the
length cap is a backstop for output that never punctuates, not a routine cut — a low
value reintroduces the original bug.

### The palette is validated, not eyeballed
Sky blue accent with an orange warn: blue and orange is the one pair that stays distinct
under every kind of colour blindness. Both modes were run through the dataviz validator
(lightness band, chroma floor, CVD separation, contrast) and every check passes; light
mode colours also clear 4.5:1 on the page background, because the verdict text is small.
Change a colour and re-run the validator rather than trusting your eye.

Dark mode is a cool blue-grey, deliberately not near-black. The first version was a warm
near-black and the first thing the user said about it was "very dark". `theme.js` also
lets them override the system setting; the CSS carries the dark tokens twice, under the
media query and under `[data-theme="dark"]`, so an explicit choice wins either way.

### Chart scales are fixed, never fitted to the data
`chart.js` gives every metric a fixed domain and a goal band. Fitting the axis to
min-max was the old behaviour and it lied: fillers going 3.0 → 3.1 → 2.9 was stretched to
full height and read as a dramatic swing. A stable scale means a flat week looks flat.
The domain only ever grows, to the next round step, when someone goes off the top of it.

### A number without a verdict is not finished
`verdict()` turns a value into "on target — barely noticeable" or "aiming for 2.0 or
fewer". Every stat tile carries one. The app measures carefully and then has to say
whether it was good, or it is just numbers.

### Direction goes in words, not arrows
`PHRASE` spells out "1.9 fewer fillers". An up arrow beside a falling filler count is
ambiguous, and colour alone fails for colourblind readers. Use `moved()`, which also
applies `MOVED` — the threshold below which a change is noise and is not mentioned at all.

### The profile is what makes it a trainer
Every mode builds its system message through `profile.system_prompt(mode, PROMPT)`, which
layers the mode's prompt, the user's override, who they are, and how they have been
speaking. Never call `settings.prompt` directly from a mode — the interviewer would stop
knowing the candidate.

`coaching_note` is deliberately defensive: it gives the model recent delivery stats *for
pacing only* and forbids mentioning them. Being told you say "um" mid-answer is exactly
what makes someone freeze, and the whole app exists to stop that.

### Schema changes need a migration
`CREATE TABLE IF NOT EXISTS` will not add a column to a database that already exists, and
users have real practice history in theirs. Add the column to `SCHEMA` *and* to
`store.ADDED_COLUMNS`, which applies it on connect. `words` and `word_rows` both arrived
this way; there is a test that runs against a database built without them.

### Paths must honour DATA_DIR
Everything the user accumulates goes under `config.DATA_DIR` (`.` natively, `/data` in the
container). Never hardcode `practice.db` or `recordings/` again, or a rebuild wipes
someone's history. Model weights resolve through `config._weights`, which accepts
`models/` or the repo root so an existing checkout keeps working.

### numpy scalars must be coerced at the boundary
faster-whisper returns numpy floats. `sum()` over comparisons of them yields `int64`,
which is neither JSON serialisable nor accepted by sqlite3 — it broke every turn once.
`fluency()` and `word_rows()` wrap every value in `int()`/`float()`; there is a regression
test for it. Any new value derived from Whisper output needs the same treatment.

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
- The default fast backend is `gemini-3.5-flash-lite` (~1.1s first token, ~$0.42/mo at
  1h/day). `gemini-flash-lite-latest` resolves to the same model; the pinned id wins
  because an alias can roll to different quota mid-habit.
- Local backends are reached through LM Studio's OpenAI-compatible server, whose URL is a
  setting. Credentials resolve in `llm.endpoint_for` at use time, never at import, so
  editing the key in the UI works without a restart.
- Client `timeout=45.0`: a cold Gemini call measured 16s and one request hung at 51s, so
  the timeout has to catch the hang without aborting the slow-but-working call. The SDK
  retries twice by default.
- `websockets` is a hard dependency. Without it uvicorn refuses the upgrade and the whole
  app sits on "connecting" — and Starlette's `TestClient` will not catch it, because it
  fakes the socket in-process. Test the wire with a real client.

## Frontend notes

- `style.css` is page chrome and forms; `data.css` is anything that displays a
  measurement. Both are linked from `index.html`.
- **Scope global element selectors.** A bare `header {}` rule styled every `<header>`,
  including the one inside each chart card — that was a 48px indent and a stray rule on
  every chart. It is `body > header` now.
- `tests/test_web.mjs` runs under plain `node` and is wired into `scripts/check.sh`. It
  exists because a chart bug shipped that every Python test passed: `SERIES.wpm.format`
  returned a Number and the review page called `.replace` on it.
- Look at the rendered page before calling a UI change done. Several of the worst
  problems here — the detached charts, the indent, a stuck spinner — were invisible in
  the source and obvious in a screenshot.

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
| Cloud TTS (Seed Audio, Gemini TTS) | $6–67/mo to replace Kokoro. Kokoro sounding bad was a sentence-splitting bug, not the voice; check the chunks before blaming the model. |
| `interview-coach-llama3-8b` style fine-tunes | Undocumented hobby LoRAs on a 2024 base. Fine-tuning teaches style, not knowledge. |
| JEV / structured-decision models | Can't hold a conversation; the scoring it would do is arithmetic. |
| LLM-based fluency scoring | Timestamps are exact and free. |
