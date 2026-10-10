# Design

Why this is built the way it is. Decisions, and the reasoning that produced them, so a
contributor can tell a deliberate choice from an accident.

## What the project is

Spoken English practice that **measures hesitation**. Not a chatbot with a microphone —
the point is the numbers: words per minute, filler rate, pause rate, and time-to-first-word,
tracked until they move.

Primary user: a non-native English speaker who freezes when speaking — in conversation,
and under the pressure of an interview. They practise about an hour a day, speaking and
listening, and are recording themselves sounding bad, which makes privacy the first
requirement, not a feature.

## Three rules that decide most arguments

1. **Audio never leaves the machine.** Whisper and Kokoro run locally; only text - the
   transcript, the profile, the resume and job posting - reaches a model, and only if the
   user picked a cloud backend. A job search sends Himalayas its search words, and only
   when the user searches. This is the one promise no hosted competitor can make, and
   nothing gets to break it.
2. **Never present an estimate as a measurement.** The backend table labels published
   latency `est.`; the `Yours` column is measured from the user's own sessions.
3. **Fluency metrics stay arithmetic.** wpm, pauses and lead-in come from word timestamps,
   and where speech starts from a voice detector, because Whisper misplaces the first word.
   Exact, free, offline, instant. A model's opinion is not an upgrade.

## Architecture

The browser is an I/O device. Everything that thinks runs in Python.

```
browser                          server (localhost)
───────                          ──────────────────
AudioWorklet ──raw PCM─────────► Whisper ──► fluency()   arithmetic, no model
                                     │
                                     ▼
                                 LLM  (Gemini, or LM Studio)
                                     │
  audio player ◄────WAV frames──── Kokoro
  transcript, timeline, charts ◄─── JSON events
                                     │
                                     ▼
                                 SQLite + recordings/
```

### Why a WebSocket

The latency design depends on overlap: sentence 1 is playing while sentence 2 is still
being generated. Request/response throws that away and it is immediately audible. One
socket carries control JSON and binary audio in both directions, and maps 1:1 onto what
`llm.stream_sentences` already yields.

### Why raw PCM, not MediaRecorder

`MediaRecorder` gives webm/opus, which Python cannot decode without ffmpeg or PyAV — a
system binary contributors will not have, and the most common "works on my machine" bug in
projects like this.

Instead the browser opens `new AudioContext({ sampleRate: 16000 })` and an AudioWorklet
yields Float32 at exactly the rate Whisper wants. `np.frombuffer` on the other side. No
decoding, no dependency, and `stt.py` needed no change. The same buffer drives the level
meter.

### Why modes keep their loops

Client-driven input does not require stateless handlers. The loop stays server-side and
awaits the socket:

```python
audio = await io.record()      # awaits an end_answer frame
await io.say(text, voice)      # ships a WAV down the socket
```

`review` is ask → listen → critique. As a loop that is four lines; as stateless handlers it
becomes a state machine someone has to debug. The mode contract did not change.

### Why no build step

Plain ES modules, no bundler, no `package.json`. Contributors on a Python project should
not need npm to fix a CSS bug. Charts are hand-drawn SVG — a chart library is 200KB for one
trend line, and a CDN would break the offline promise.

## Interface

**Focus while you speak.** While you are answering there is only the mic: the session
panel dims and nothing changes on screen. A dashboard you can read mid-answer gives you
somewhere to hide and something to perform for.

**The session between answers.** Between answers the page shows the whole session so far —
each metric with a sparkline, one point per answer — the clock against the goal you set,
and your last answer in detail. Per-answer numbers alone could not show whether an hour of
practice was getting better or worse; this was asked for after the first real session.

**Listen first.** What the partner says is blurred until you choose "show text". Reading it
would turn a listening exercise into a reading one.

**Calm and minimal.** Generous white space, one accent colour, soft type. The user is
already nervous; the tool should not add to it.

The three things that justify a browser existing at all:

- **Replay your own answer.** Hearing yourself say "mmmm" beats being told you did.
- **Fillers highlighted in the transcript.** You see them.
- **A pause timeline.** Your answer as a bar with the silences as gaps. A two-second hole is
  visceral in a way `longest_pause: 2.0` never is.

Parity with a CLI would not have been worth building.

### Charts must not flatter

The first version scaled each trend line from its own minimum to its own maximum. That
renders a week where nothing changed as a mountain range, and it is the same failure as
presenting an estimate as a measurement — the app's whole claim is that its numbers are
real. Scales are fixed now, with the target drawn as a band, so the reader can see both
where they are and how far that is from where they want to be.

## Data

| Thing | Where | Why |
|---|---|---|
| Sessions, turns, metrics | SQLite `practice.db` | queryable, one file, stdlib |
| Recorded answers | `recordings/<session>/<turn>.wav` | prunable, streams to `<audio>` with range requests; BLOBs would bloat the DB |
| Settings | SQLite `settings` table | survives restarts, editable from the UI |
| Secrets | `.env`, never returned to the browser | the API key is write-only over the wire, masked on read |

Recordings are kept forever by default: they never leave the machine, so deleting them
protects nothing. `audio_retention_days` deletes older ones for anyone short of disk,
checked by mtime every ten minutes while the server runs (`clock.py`).
Roughly 1MB per answer, ~40MB per hour of practice, so steady state is a few hundred MB.
There is a visible delete-everything button, because the whole pitch is that this data is
yours.

## Extension points

Three places are deliberately **data, not branches**. Adding to any of them touches one
place and nothing else.

| To add | Do | Never |
|---|---|---|
| A mode | one file in `src/coach/modes/` | add a branch in `main.py` |
| A model | one row in `backends.CATALOGUE` | branch on a backend key |
| A setting | one row in `settings.SPEC` | hand-write a form field |

The settings UI renders itself from `SPEC`, so a new knob appears in the browser with no
frontend change.

## Rejected

| Option | Why not |
|---|---|
| Bigger local model for conversation | 18GB M3 Pro: 4B makes errors, 9B is too slow. Local is the offline fallback, not the default. |
| Speech-to-speech (Gemini Live) | ~$17/mo and a 15-min session cap — 4+ reconnects per hour — and it makes the fluency metrics harder to extract. |
| Cloud TTS | $6–67/mo to replace Kokoro, which is free, local and good. The interviewer's voice has no effect on the user's fluency. |
| MediaRecorder / webm | needs ffmpeg server-side. See above. |
| React, Vue, a bundler | a build step on a clone-and-run project costs more contributors than it gains. |
| LLM-scored fluency | timestamps are exact and free. |
| Keeping the CLI | two front ends, one of them unused. `sounddevice` and its PortAudio dependency went with it. |
