# Contributing

## One command

```bash
make check
```

Runs ruff, the formatter, the line budget and the tests. Green before you push.
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
tests/               plain asserts, no framework
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
there is nothing to argue about. Two conventions it cannot check:

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

async def run(endpoint, transcriber, speaker) -> list[dict]:
    ...                  # endpoint bundles .client, .model and .extra
```

Copy `src/coach/modes/talk.py` and change the prompt.

## Adding a model

One row in `CATALOGUE` in `src/coach/backends.py`. It appears in the picker the moment
LM Studio serves it. Never branch on a backend key.

## Adding a setting

One row in `SPEC` in `src/coach/settings.py`. The settings screen renders itself from
that, so there is no frontend change and no hand-written form field. Secrets set
`secret=True` and are never sent back to the browser.

## Tests

Plain `assert` in `tests/test_coach.py`, run with `python tests/test_coach.py`. No
pytest, no fixtures, no mocks beyond reassigning a module attribute.

Non-trivial logic gets one test — a branch, a parser, a money or timing path. Trivial
one-liners do not; YAGNI applies to tests too.

## Honesty rules

Two things this project refuses to fudge, because the whole point is measuring something
real:

- **Never present an estimate as a measurement.** The picker's `Latency` column is
  labelled `est.` where it is a guess; `Yours` is measured from the user's own sessions.
- **Fluency metrics stay arithmetic.** wpm, pauses and lead-in come from word timestamps
  and are exact. Do not replace them with a model's opinion.
