# Contributing

## One command

```bash
make check
```

Runs ruff, the formatter, mypy, the line budget, hadolint and actionlint (when installed)
and the tests with coverage. Green before you push.
`make` on its own lists every target.

## Running it

`make run` is native and fastest. `make up` runs the same thing in Docker, which is the
right choice if you want a clean environment or you are not on a Mac. The image carries
no model weights: Kokoro is mounted from `models/` and Whisper downloads once into a
named volume.

## Layout

Exactly **one code file lives at the repo root**: `main.py`, the entry point. Everything
else has a home.

```
main.py              the only root module - argument parsing and startup
src/coach/           the package
src/coach/modes/     one file per mode, discovered automatically
tests/               pytest, one file per area; conftest.py holds the fixtures
scripts/             checks and tooling
web/                 the browser app: plain ES modules, no build step
```

There is no bundler and no `package.json` on purpose. Edit `web/*.js` and reload.

## The 300-line budget

No source file may exceed **300 lines**. `scripts/check_lines.py` enforces it and warns
at 240.

The reason is not aesthetics. Both people and coding agents have to load a file before
they can change it, and an agent pays for every line twice — once reading, once
reasoning. Files that stay small stay cheap to work on, and a repo of small files can be
understood a piece at a time instead of all at once.

When a file crosses the line, **split it along a real seam** — a mode, a concern, a
layer. Two tangled 150-line files are worse than one coherent 300-line file. If a file
genuinely belongs together and has outgrown the budget, raise `LIMIT` and say why in the
commit; the cap is a prompt to think, not a law.

## Style

`ruff` is the standard, configured in `pyproject.toml`. `ruff format` decides layout, so
there is nothing to argue about. Beyond style, it holds every function to a size:

- **Complexity at most 10, branches at most 12, statements at most 50.** A function that
  outgrows them is split along its sections (see `sheet.render`), not excused.
- **At most five positional arguments.** Past that, a call stops saying what it passes:
  make the rest keyword-only, after a `*`.
- **Security checks (bandit) are on.** The few deliberate exceptions are project-wide in
  `pyproject.toml` with their reason, or a `# noqa` on the line saying why.

`mypy` type-checks everything. The app is fully annotated; tests need no annotations, but
their bodies are checked, so an optional value is narrowed with `assert x is not None`
before it is used.

The Dockerfile is linted by hadolint and the workflows by actionlint. CI installs both at
pinned versions; `brew install hadolint actionlint` runs them locally too.

Two conventions no tool can check:

- **Comments explain why, not what.** The code says what it does.
- **Mark deliberate shortcuts** with a `ponytail:` comment naming the ceiling and the
  upgrade path, e.g. `# ponytail: naive sentence heuristic; swap in a real segmenter if
  it mis-splits`. A known shortcut that is written down is technical debt; one that is
  not is a trap.

`# fmt: off` is fine for data tables where column alignment carries meaning — see
`backends.py` — and nowhere else.

## Adding a mode

Drop a file in `src/coach/modes/`. It is discovered automatically; no registry to update
and no branch in `main.py` to extend.

```python
HELP = "walk through a system design out loud"
ENDPOINT = "deep"        # "fast" for conversation, "deep" for analysis

async def run(endpoint, io) -> None:
    said = await io.answer()                       # hear, score and save one answer
    await io.reply(endpoint, messages)             # speak the model's reply as it streams
```

A conversation is one call to `converse()` in `src/coach/modes/_converse.py` — copy
`src/coach/modes/talk.py` and change the prompt. The full contract is in
`src/coach/modes/__init__.py`.

## Adding a model

One row in `CATALOGUE` in `src/coach/backends.py`. It appears in the picker the moment
LM Studio serves it. Never branch on a backend key.

## Adding a setting

One row in `SPEC` in `src/coach/settings.py`. The settings screen renders itself from
that, so there is no frontend change and no hand-written form field. Secrets set
`secret=True` and are never sent back to the browser.

## Adding a profile field

One row in `FIELDS` in `src/coach/profile.py`. It appears on the profile page and inside
every system prompt automatically. `label` is the question the form asks; `term` is how it
reads to the model.

## Adding a page

A module in `web/views/` exporting `render(root, params, query)`, and one `route()` line in
`web/app.js`. Add an optional `leave()` if it holds anything that needs tearing down — the
practice view uses it to close its socket and release the microphone.

## Tests

pytest, one file per area: `test_stt.py` (scoring an answer), `test_llm.py` (talking to
models), `test_store.py` (settings, sessions, recordings), `test_server.py` (the guard,
backends, which modes are open), `test_profile.py`, `test_history.py`, `test_modes.py`,
`test_reports.py` (Telegram, with Relay faked) and `test_sheet.py`. `test_web.mjs` covers
the charts under plain `node`. `make check` runs them all with coverage, as CI does, and
fails below the floor in `pyproject.toml` - raise it as tests are added, never lower it.

- Every test gets its own empty database and none of your environment (`conftest.py`): a
  key in `.env` once hid a crash that only happened without one.
- Fixtures over setup code: `counted` makes a session that counts, `telegram` fakes Relay,
  `lessons` gives a session the coach's summary.
- Never call a real model or a real Relay. Fake the one function that reaches it with
  `monkeypatch`.
- Tables of cases are `pytest.mark.parametrize`, and a test's name says what it proves.
- Warnings are errors: a leaked socket or a deprecation fails the run.
- Every bug fix comes with a test that fails before the fix.

`make e2e` runs `tests/test_wire.py`: the real server over a real WebSocket, a spoken
answer synthesised by Kokoro, and a fake model. It needs the Kokoro weights, so plain
`pytest` skips it (`-m "not e2e"`) - run it before you push anything that touches the
session.

## Charts

Three rules, all learned the hard way:

1. **Fixed scales.** Never fit an axis to min-max — it turns noise into a story. Domains
   and goal bands live in `SERIES` in `web/chart.js`.
2. **Every number gets a verdict.** `118 wpm` on its own tells the reader nothing.
3. **Direction in words.** "1.9 fewer fillers", not "↑ 1.9". Arrows are ambiguous when
   lower is better, and colour alone excludes colourblind readers.

Add a metric by adding a row to `SERIES`; the charts, tiles and comparison sentences all
build from it.

## Honesty rules

Two things this project refuses to fudge, because the whole point is measuring something
real:

- **Never present an estimate as a measurement.** The picker's `Latency` column is
  labelled `est.` where it is a guess; `Yours` is measured from the user's own sessions.
- **Fluency metrics stay arithmetic.** wpm, pauses and lead-in come from word timestamps
  and are exact. Do not replace them with a model's opinion.
