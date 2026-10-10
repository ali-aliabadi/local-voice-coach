# local-voice-coach

[![check](https://github.com/ali-aliabadi/local-voice-coach/actions/workflows/check.yml/badge.svg)](https://github.com/ali-aliabadi/local-voice-coach/actions/workflows/check.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Spoken English practice that **measures your hesitation**. You talk in the browser, a
model plays the other side, and every answer is scored for speed, filler words, pauses
and how long you took to start. A coach writes up your grammar and phrasing afterwards.

Whisper and Kokoro run locally, so your voice never leaves your machine. Only transcript
text goes to the model, and with a local model nothing leaves at all.

## Setup

You need [uv](https://docs.astral.sh/uv/) and `make`. Docker is optional.

**1. Gemini key.** Free, no card: [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
To stay offline, skip it and load a model in [LM Studio](https://lmstudio.ai/); it shows
up in the model picker. With LM Studio running, a model there also writes the notes, study
sheet and verdict whenever Gemini cannot - a spent budget or daily quota, no internet.

**2. Relay (optional): reports on Telegram.** Needs a
[Relay](https://github.com/ali-aliabadi/relay) server. Its admin runs:

```bash
relay clients create voice-coach                  # prints this app's API key once
relay recipients add <you> --name "Your Name"     # you, as a Relay user
relay recipients link <you> @your_telegram_name   # then open the bot and tap Start
```

On a Docker-hosted Relay, prefix each with `docker compose exec relay`.

**3. `.env`** in the repo root:

```bash
GEMINI_API_KEY=...
RELAY_URL=https://relay.example.com
RELAY_API_KEY=rk_...
RELAY_APP=voice-coach
RELAY_USER=<you>
```

Set `RELAY_USER` to your own recipient's username; there is no default. At the start
the app checks, sending nothing, that the key works and that `RELAY_USER` has Telegram
linked, and the Today page says what is wrong if not. Leave the `RELAY_*` lines out to
keep Telegram off.

**4. Run.**

```bash
make install   # Python dependencies
make run       # fetches the voice weights once, then opens http://127.0.0.1:8000
```

Or `make up` to run it in Docker (`make logs`, `make down`). On a Mac, native is faster.

Then fill in your [profile](http://127.0.0.1:8000/profile) so the partner knows who it
is talking to. For interviews, add your resume (PDF, Word, ODT, text or Markdown) and, if
you have one, the job posting: the interviewer reads both before you start.

## Modes

| Mode | What it is |
|---|---|
| **talk** | Everyday conversation with a partner who remembers your last sessions |
| **roleplay** | A real-life scene: a restaurant, a doctor, a return, a new colleague |
| **retell** | Hear a short story, tell it back |
| **repeat** | The 4/3/2 drill: one topic in 90, 60 and 45 seconds |
| **shadow** | Repeat a sentence straight back |
| **interview** | A whole interview built on your resume, from hello to your questions for them |
| **panel** | Three interviewers, closer to a real onsite |
| **scenario** | Describe the interview you want, out loud, and it plays that interviewer |
| **review** | One hard technical question, then a written critique out of 10 |

More modes unlock as you complete sessions.

After an interview, the session page has the interviewer's verdict: a rating out of 10,
whether they would hire you, and why. Telegram gets only the rating and the decision.
[Jobs](http://127.0.0.1:8000/jobs) lists real remote postings from
[Himalayas](https://himalayas.app); pick one and your next interview is for that job.

## The numbers

| Metric | Meaning | Aim |
|---|---|---|
| **wpm** | words per minute while speaking | up, ~140–160 |
| **fillers** | "um", "uh", "mmm" per 100 words | 2 or fewer |
| **pauses** | silences over 0.6s, per minute | down |
| **lead-in** | seconds before your first word | down |

Whisper drops some fillers even when told not to, so filler counts are a floor. The rest
come from word timestamps and are exact.

**Talking** in Settings is *space* (tap or press space to start and stop) or *hybrid*: the
mic stays open, your voice starts the answer, a pause ends it, and talking over the
partner cuts in, as in a real conversation. Lead-in then counts from the end of their
sentence, not from a key press. Use headphones, or the partner's voice can cut itself off. Every session is kept: `/history` replays them,
`/progress` charts the trend.

## Your data

Sessions and recordings stay in `data/` (Docker) or the repo root (native), never
uploaded. Recordings are kept forever, about 40MB an hour, unless you set a number of
days in Settings. `make reset` erases everything.

## Contributing

A mode is one file, a model one row, a setting one row. See
[CONTRIBUTING.md](CONTRIBUTING.md) and [DESIGN.md](DESIGN.md); `make check` runs what CI
runs.

## License

[Apache-2.0](LICENSE)
