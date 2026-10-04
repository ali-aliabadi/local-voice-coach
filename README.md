# local-voice-coach

Spoken interview practice that **measures your hesitation**.

You answer out loud in the browser, an interviewer digs into what you said, and every
answer is scored: words per minute, filler words, pauses, and how long you took to start
talking. Then you listen back to yourself.

**Your voice never leaves your machine.** Whisper and Kokoro run locally. Only transcript
text reaches a model, and only if you choose a cloud backend — pick a local one and
nothing leaves at all.

<!-- TODO: 20-second screencast goes here. It converts better than anything written below. -->

Built for one problem: *"I can't speak confidently in interviews. There are a lot of mmmm
and my sentences take a long time to form."* Most tools can't even measure that, because
speech-to-text is trained to tidy disfluencies away before anything sees them.

## Setup

```bash
make install     # Python dependencies
make run         # fetches the voice weights, then serves http://127.0.0.1:8000
```

Or in Docker:

```bash
make up          # build and start
make logs        # watch it come up
make down
```

`make` on its own lists everything.

Add a Gemini key in Settings (free, no card, from
[aistudio.google.com/apikey](https://aistudio.google.com/apikey)), or skip it and use a
local model through [LM Studio](https://lmstudio.ai/).

**Native is faster than Docker on a Mac.** Docker runs Linux in a VM there, so Whisper
gets less CPU and no access to the Neural Engine. Use Docker for a clean or shared
environment; use `make run` for daily practice.

The container reaches LM Studio on your machine at `host.docker.internal:1234` — already
configured, since `localhost` inside a container means the container.

## It knows who you are

Fill in [your profile](http://127.0.0.1:8000/profile) — target role, level, the stack you
actually use, and what you want to get better at — and the interviewer reads it before
every session. It pitches difficulty at your level, digs into the projects you named, and
pushes on the thing you said you freeze on. It never reads any of it back at you.

It also sees how you have been speaking lately, and asks shorter, more concrete questions
when you have been hesitating. It is told, in the prompt, never to mention your speech:
being corrected mid-answer is what makes people freeze.

## Modes

| Mode | What it is |
|---|---|
| **talk** | Everyday conversation, not an interview — a friendly partner chats about ordinary things and talks enough to give you something to listen to. Fast replies, every answer scored. |
| **panel** | Three interviewers with distinct voices — a hiring manager, a staff engineer, and a bar raiser who pushes back. Closer to a real onsite. |
| **review** | One hard technical question, then a written critique: what held up, what was vague, what a real interviewer would probe next. Deliberately slow. |

Tap the circle to answer, tap again when you're done. Space works too.

## The numbers

| Metric | Meaning | Direction |
|---|---|---|
| **wpm** | words per minute while actually speaking | up — native conversational is ~140–160 |
| **fillers** | "um", "uh", "mmm", "er", "hmm" | down |
| **pauses** | silences past your threshold (0.6s) mid-answer | down |
| **lead-in** | seconds before your first word | down — this is *"sentences take long to form"* |

After each answer you get the transcript with **every filler highlighted**, a **timeline**
of your answer with the silences drawn as gaps, and **playback of your own voice**.

**Every session is kept and replayable.** End one and you land on its full review: the
whole conversation, each answer scored, the highlighted transcript and timeline for each,
and your recordings. `/history` lists them all; `/progress` totals everything you have
ever done and charts the four numbers over time.

Filler counts are a floor, not a census: Whisper drops some disfluencies even with the
prompt biasing it toward verbatim. Pauses, wpm and lead-in come from word timestamps and
are exact.

## Cost

Measured on a real turn: 995 input tokens, 20 output. At ~40 answers (about an hour) a day:

| Backend | If billed | First token |
|---|---|---|
| `gemini-3.5-flash-lite` | **$0.42/month** | ~1.1s |
| `gemini-3.8-flash` | ~$1.08/month | ~3–9s |
| anything local | **free** | see below |

Free tier covers roughly 500 requests/day, well above the ~40 an hour needs. Run a local
model and it's free and offline regardless.

The picker shows published latency next to **Yours** — the average measured from your own
past sessions. Trust that column, not the estimate.

## Offline

Start LM Studio, load any of these, and it appears in the picker automatically:

| Model | Role | RAM |
|---|---|---|
| [LFM2.5 1.2B](https://lmstudio.ai/models/liquid/lfm2.5-1.2b) | talk | 0.95GB |
| [Ministral 3 3B](https://lmstudio.ai/models/mistralai/ministral-3-3b) | talk | 2GB |
| [Gemma 4 E2B](https://lmstudio.ai/models/google/gemma-4-e2b) | talk | 4GB |
| [Nemotron 3 Nano 4B](https://lmstudio.ai/models/nvidia/nemotron-3-nano-4b) | talk | 5GB |
| [Gemma 4 E4B](https://lmstudio.ai/models/google/gemma-4-e4b) | both | 6GB |
| [Bonsai 27B](https://lmstudio.ai/models/prism-ml/bonsai-27b) | review | 4GB — 27B reasoning, keeps 94.6% of FP16 |
| [Qwen3.5 9B](https://lmstudio.ai/models/qwen/qwen3.5-9b) | review | 7GB |
| [gpt-oss-20b](https://lmstudio.ai/models/openai/gpt-oss-20b) | review | 12GB |

Local reasoning models need a generous token budget — Bonsai-27B returns an *empty* reply
if thinking eats it all. Raise "Review max tokens" in Settings if that happens.

## Your data

Sessions, metrics and recordings live in `data/` (or the repo root when running natively
without `DATA_DIR`). Both are gitignored and neither is ever uploaded. Recordings
auto-delete after 7 days, Settings has a button that erases everything, and `make reset`
does the same from the terminal.

## Contributing

Adding a mode is one file. Adding a model is one row. Adding a setting is one row, and the
form builds itself. See [CONTRIBUTING.md](CONTRIBUTING.md) and [DESIGN.md](DESIGN.md).

```bash
./scripts/check.sh      # ruff, formatter, 300-line budget, tests
```
