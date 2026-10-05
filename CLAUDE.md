# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Project Overview

Spoken English practice for non-native speakers. The user talks out loud — everyday
conversation, roleplays, retelling, drills, or a software-engineering interview — a model
plays the other side, every answer is scored for fluency so hesitation can be tracked over
time, and a coach writes up the language afterwards. Intended to be published for others
to use and contribute to.

The goal behind every design choice: the user wants to cut filler words ("mmmm"), shorten
the time it takes to form a sentence, and understand spoken English by ear. They practise
about an hour a day.

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
                                     │
                     coach.py (notes, after)   reports.py ──► Relay ──► Telegram
```

## Commands

```bash
make install                         # uv sync: exactly what uv.lock pins, ruff included
make models                          # Kokoro weights into models/ (~340MB, once)
make run                             # native, serves http://127.0.0.1:8000
make up / down / logs                # the same thing in Docker
make check                           # ruff, format, mypy, line budget, pytest + coverage (CI)
make e2e                             # real server, real socket, a spoken answer
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
| `src/coach/llm.py` | endpoints, streaming, retries |
| `src/coach/chunks.py` | where to cut a streaming reply so it can be spoken |
| `src/coach/backends.py` | the model catalogue and reachability probing |
| `src/coach/store.py` | SQLite: writing sessions, turns, settings, retention |
| `src/coach/history.py` | reading it back: one session, all sessions, totals; `RATES` |
| `src/coach/today.py` | today's minutes, the streak, the last session's advice |
| `src/coach/profile.py` | who the user is, past-session recaps, the system prompt |
| `src/coach/coach.py` | the second model: notes on each answer, the session summary |
| `src/coach/clock.py` | jobs that run on a timer while the server is up |
| `src/coach/relay.py` | the Relay client: Telegram, off unless `RELAY_*` is set |
| `src/coach/reports.py` | what goes to Telegram and when |
| `src/coach/picture.py` | the charts as PNG, for Telegram (Pillow) |
| `src/coach/server/` | `app.py` assembly + websocket, `api.py` JSON routes, `session.py` the `io` modes talk to, `guard.py` localhost-only, `models.py` loaded models |
| `src/coach/modes/` | one file per mode, discovered automatically; `_`-prefixed files are helpers |
| `web/` | plain ES modules, no build step; `views/` is one file per route; `screen.js` draws the practice page that `views/practice.js` drives |
| `models/` | Kokoro weights, gitignored, fetched by `make models` |
| `data/` | sessions, metrics, recordings — gitignored, mounted as a volume |

## House rules

- **One code file at the repo root**: `main.py`. Everything else lives in `src/coach/`,
  `tests/` or `scripts/`.
- **300 lines per file, hard cap**, warned at 240, enforced by `scripts/check_lines.py`.
  An agent pays for every line twice — reading it and reasoning about it. When a file
  crosses, split along a real seam; two tangled files are worse than one coherent one.
- **`ruff` and `mypy` are the standard**, configured in `pyproject.toml`: complexity 10,
  five positional arguments, bandit on, the app fully annotated. Split, don't excuse.
- **`ruff` formats**, configured in `pyproject.toml`. `./scripts/check.sh` runs
  everything CI would. `# fmt: off` only for data tables where alignment carries meaning.
- Full detail in [CONTRIBUTING.md](CONTRIBUTING.md).

## The mode contract

**Adding a mode must never require editing another file.** Modes are discovered with
`pkgutil` in `src/coach/modes/__init__.py`. A mode declares `HELP`, `ENDPOINT` (`"fast"`
or `"deep"`), and `async def run(endpoint, io)`; optionally `UNLOCK`, the sessions done
before it opens. A first session sees only `talk` (0); interviews open at 2.

`io` is the browser, for one session: `await io.answer()` hears, scores and saves an
answer; `await io.reply(endpoint, messages)` speaks the model's reply as it streams and
handles failure (it returns None and offers a retry); `io.save_turn()`, `io.send()` and
`io.prior_turns()` cover the rest. A conversational mode is one call to `converse()` in
`modes/_converse.py`. Modes loop forever and never catch `SessionClosed` — the server
catches it when the user stops.

The session id lives on `io`, never in a module global: two tabs each own a session.

Do not reintroduce a branch on mode name. A mode needing a different backend names a role
in `ENDPOINT`; `backends.CATALOGUE` does the rest.

## Key decisions

### Fluency metrics are arithmetic, not a model
`fluency()` counts words and measures gaps between timestamps. Deliberately not an LLM
call: counting is exact, free, offline and instant. Do not replace it.
The `pause_seconds` setting (0.6) is a calibration knob, not a magic number.

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
mid-sentence and it read as bad text-to-speech. `chunks.split_for_speech` finds the last
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

### `talk` is conversation practice, not an interview
`talk` is everyday chat for a non-native speaker: the partner speaks natural English
(contractions, phrasal verbs) in 2-3 sentences so there is something to listen to, and
asks open questions so the user does most of the speaking. It calls
`system_prompt(..., interview=False)`, which passes only `profile.PERSONAL` (name, first
language): stack, role and focus pulled every chat back to engineering. It may echo a
garbled sentence back naturally ("Oh, so you ended up...") but never points it out, so
the no-correction rule still holds.

### Correction lives with the coach, not the partner
The conversation partner never corrects the user — being corrected mid-answer is what
makes people freeze. `coach.py` is a second model that reads each answer in the
background (never awaited by the conversation) and writes notes read after the session,
then a session summary whose `recap` becomes `talk`'s memory of past sessions. Its
prompts forbid blaming the speaker for speech-recognition errors: a "fix" for a word
Whisper misheard, or for the transcriber's spelling, is the worst kind of note. Coach
requests go one at a time and wait out 429s — the free tier for Gemini 3.8 Flash is 5
requests a minute, and catching up a 23-answer session at once had 20 refused. The
default is Flash-Lite: notes as useful as Flash's, in 2s instead of 20s.

### The study sheet is drawn, not typeset
`sheet.py` has a model write the sheet's content as JSON after the summary; `layout.py`
draws it with Pillow, which already draws the charts and can save pages as a PDF - so the
PDF and the Telegram images come from one renderer and no PDF library is added. Pillow's
own font has no dashes, arrows or accents, so `make models` fetches Inter into `models/`;
without it the sheet still renders, in plain ASCII. The sheet's prompt insists a fix
keeps the speaker's meaning - Flash-Lite once "fixed" a misheard phrase into one meaning
the opposite. The coach's background tasks wait only for those queued before them
(notes, then summary, then sheet): waiting on all the others deadlocked summary and sheet.
Gemini 3.8 Flash's free tier is 20 requests a day; `llm.patiently` waits out per-minute
limits but reports a used-up daily quota at once instead of waiting hours.

### Telegram through Relay is optional and environment-only
`relay.py` is off unless `RELAY_URL`, `RELAY_API_KEY` and `RELAY_APP` are set. The key
is read from the environment only — never a setting, never logged; logs carry message
ids, never contents. `reports.py` holds what is sent and when; each message remembers
what it sent under `relay:` keys in the settings table, so a restart never repeats one.
The charts are drawn server-side by `picture.py` (Pillow) so a report never depends on
a browser tab still being open; `picture.SERIES` mirrors `SERIES` in `chart.js`, and
a test fails if they drift.

### A session counts at 2 answers and 2 minutes
Anything shorter is a try: `history.counted()` leaves it out of the history list, streaks,
totals, trends, mode unlocks, the coach's summary, the study sheet and Telegram. The rule
is one subquery; use it rather than re-deriving "has answers".

### The app runs only while you practise
It is started for a session and stopped after, so nothing may depend on it being up at a
given time. Everything sent to Telegram goes when a session ends, last week's report
included; a daily reminder was removed because it could only ever fire at someone already
in the app. Quitting waits for the coach's queue (`app.finish_up`), and a second Ctrl-C
skips it.

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
budget, exactly like `gemini-3.8-flash` did at 120. The `review_max_tokens` setting is 2500, and
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
- Tests are pytest, one file per area, each with its own empty database and none of
  the environment (`tests/conftest.py`). Bug fixes come with a test that fails without
  them. Coverage has a floor in `pyproject.toml`; raise it, never lower it.
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
