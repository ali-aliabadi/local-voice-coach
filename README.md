# local-voice-coach

Spoken software-engineering interview practice. You answer out loud, an interviewer digs
into what you said, and every answer is scored for **fluency** — words per minute, filler
words, pauses, and how long you take to start talking.

Your speech never leaves the machine. Whisper (transcription) and Kokoro (voice) run
locally; only transcript text goes to the model. The review mode can run fully offline.

Built for one specific problem: *"I can't speak confidently in interviews. There are a lot
of mmmm and my sentences take a long time to form."* Most practice tools can't even measure
that, because speech-to-text is trained to tidy disfluencies away before anything sees them.

## Setup

```bash
uv pip install -e .
echo 'GEMINI_API_KEY=...' > .env      # free key: https://aistudio.google.com/apikey
```

Download `kokoro-v1.0.onnx` and `voices-v1.0.bin` into the repo root from
[kokoro-onnx releases](https://github.com/thewh1teagle/kokoro-onnx/releases). Both are
gitignored. `.env` is read at startup; a real environment variable overrides it.

## Modes

```bash
python main.py                        # asks: which mode, then which interviewer
python main.py --mode talk            # skip the mode prompt
python main.py --backend bonsai27     # skip the interviewer prompt
python main.py --stats                # your progress across past sessions
```

Run with no arguments and it walks you through a tree — mode first, then a table of
every backend that can play that mode, with what is actually reachable right now:

```
┌─ Interviewer for 'talk' ─────────────────────────────────────────────────────────
│ #   Backend                Latency        Yours     Cost      Free  RAM     Notes
│ 1   Gemini 3.5 Flash-Lite  1.1s measured  1.1s n=3  $0.42/mo  no    cloud   ...
│ 2   Gemini 3.8 Flash       3-9s measured  —         $1.08/mo  no    cloud   ...
│ -   LFM2.5 1.2B            <0.5s est.     —         free      yes   0.95GB  (not loaded in LM Studio)
│ 3   Gemma 4 E4B            ~1s est.       —         free      yes   6GB     ...
└──────────────────────────────────────────────────────────────────────────────────
```

**Latency** is published or estimated. **Yours** is the mean first-token time measured
from your own past sessions — the number to trust. `-` rows are unreachable right now,
with the reason shown.

Pull the plug and the cloud rows go dark; it falls back to whatever LM Studio is serving.
If nothing at all is reachable it says so and exits instead of hanging.

Set `MODE=talk` and `BACKEND=flash-lite` in `.env` once you have a favourite, and the
prompts disappear entirely.

| Mode | What it is | Endpoint |
|---|---|---|
| **talk** | One interviewer, fast replies, scored per answer. Built for reps. | fast |
| **panel** | Three interviewers with distinct Kokoro voices — a hiring manager, a staff engineer, and a bar raiser who pushes back. Closer to a real onsite. | fast |
| **review** | One hard technical question, then a written critique: what held up, what was vague, what a real interviewer would probe next, and a stronger answer. Deliberately slow. | deep |

Any key starts your answer, any key ends it, `q` finishes the session.

## The numbers

```
You (820ms): "So, um, I worked on a payment service that..."
   📊 118 wpm · 4 fillers · 3 pauses (longest 1.9s) · started after 2.4s
```

| Metric | Meaning | Direction |
|---|---|---|
| **wpm** | words per minute while actually speaking | up — native conversational is ~140–160 |
| **fillers** | "um", "uh", "mmm", "er", "hmm" | down |
| **pauses** | silences over `PAUSE_SECONDS` (0.6s) mid-answer | down |
| **lead-in** | seconds before your first word | down — this is *"sentences take long to form"* |

Every turn is written to `practice.db` (SQLite, gitignored). `--stats` reads it back:

```
Date              Mode    Answers   WPM  Fillers  Pauses  Lead-in
───────────────────────────────────────────────────────────────
2026-09-27 19:31  talk         14   112      4.1     3.2     2.8s
2026-10-04 20:02  talk         18   126      2.4     2.1     1.6s
───────────────────────────────────────────────────────────────
change                              +14     -1.7    -1.1    -1.2s
   (wpm up is good; fillers, pauses and lead-in down is good)
```

That trend is the whole point. `english_practice_log.md` is the old markdown log, kept
for history but no longer written to.

Filler counts are a **floor, not a census**: Whisper drops some disfluencies even with
`DISFLUENCY_HINT` biasing it toward verbatim. Pauses, wpm and lead-in come from word
timestamps and are exact.

## Cost

Measured on a real full-context turn: **995 input tokens, 20 output.** At ~40 turns
(about an hour) a day:

| Model | If billed | First token |
|---|---|---|
| `gemini-3.5-flash-lite` (talk, panel) | **$0.42/month** | ~1.1s |
| `gemini-3.8-flash` (review) | ~$1.08/month | ~3–9s |

On the free tier it is $0 with a cap around 500 requests/day, well above the ~40 an hour
needs. A response carrying `serviceTier: "standard"` means you are being billed — check
your tier in AI Studio. Either way it is about a dollar a month. Prices double 2027-01-01.

### Offline

Start [LM Studio](https://lmstudio.ai/) and load any model from the table below; it appears
in the picker automatically and everything runs with no internet and no bill.

| Backend | Role | RAM | Why you'd pick it |
|---|---|---|---|
| [LFM2.5 1.2B](https://lmstudio.ai/models/liquid/lfm2.5-1.2b) | talk | 0.95GB | emergency fallback — fastest, weakest |
| [Ministral 3 3B](https://lmstudio.ai/models/mistralai/ministral-3-3b) | talk | 2GB | Apache 2.0, light and chatty |
| [Gemma 4 E2B](https://lmstudio.ai/models/google/gemma-4-e2b) | talk | 4GB | effective 2B with a reasoning toggle |
| [Nemotron 3 Nano 4B](https://lmstudio.ai/models/nvidia/nemotron-3-nano-4b) | talk | 5GB | hybrid Mamba2, cheap 256K context |
| [Gemma 4 E4B](https://lmstudio.ai/models/google/gemma-4-e4b) | both | 6GB | best offline all-rounder |
| [Bonsai 27B](https://lmstudio.ai/models/prism-ml/bonsai-27b) | review | 4GB | 27B reasoning at ~4GB, keeps 94.6% of FP16 |
| [Qwen3.5 9B](https://lmstudio.ai/models/qwen/qwen3.5-9b) | review | 7GB | dense 9B reasoner, 262K context |
| [gpt-oss-20b](https://lmstudio.ai/models/openai/gpt-oss-20b) | review | 12GB | 21B MoE, 3.6B active, ~21 tok/s on an M3 Pro |

**Local reasoning models need a big token budget.** Bonsai-27B returned an *empty* reply at
`max_tokens=500` because thinking consumed all of it. `REVIEW_MAX_TOKENS` is 2500 for this
reason, and an empty reply now prints an explanation instead of failing silently.

Vision-only models were left out: [GLM-4.6V Flash](https://lmstudio.ai/models/zai-org/glm-4.6v-flash)
is a strong VLM, but nothing here looks at images.

## Adding a mode

Drop a file in `coach/modes/`. It is discovered automatically — no registry, no branch in
`main.py` to extend.

```python
# coach/modes/whiteboard.py
HELP = "walk through a system design out loud"
ENDPOINT = "deep"  # "fast" for conversation, "deep" for analysis


async def run(endpoint, transcriber, speaker) -> list[dict]:
    ...  # endpoint bundles .client, .model and .extra
    return scores  # the fluency dicts you collected
```

Copy `coach/modes/talk.py`, change the prompt, and you have a new mode.

## Layout

```
main.py                  the only code file at the root: parse args, start up
src/coach/config.py      every tunable in the project — start here
src/coach/audio.py       microphone in, speaker out
src/coach/stt.py         Whisper + the fluency arithmetic
src/coach/llm.py         endpoints, streaming, sentence chunking
src/coach/backends.py    the catalogue: every model, its cost and reachability
src/coach/picker.py      the startup tree
src/coach/store.py       SQLite: every turn, and measured latency per backend
src/coach/session.py     the scoreboard and the progress trend
src/coach/modes/         one file per mode, self-registering
tests/                   plain asserts, no framework
scripts/                 check.sh, check_lines.py
```

No source file exceeds **300 lines** — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Test

```bash
./scripts/check.sh      # ruff, formatter, line budget, tests
```

Plain asserts, no framework. Note `python` may not be on your PATH — use `./.venv/bin/python`.
