# Security

This app holds personal things: recordings of your voice, transcripts of what you said,
and an API key. It is built to keep them on your machine.

## What protects them

- **Local only.** The server listens on 127.0.0.1. Requests must name a local host
  (stopping DNS rebinding), and anything that changes state must come from the app's own
  pages (stopping other websites from calling it). See `src/coach/server/guard.py`.
- **Nothing leaves without you.** Audio never leaves the machine. Transcripts go to the
  model you choose; Telegram reports carry numbers, a chart and, only if you allow it, the
  coach's lessons. The API key is never sent to the browser, and the Relay key is read
  from the environment only, never logged.
- **Checked on every change.** CI runs gitleaks over the whole history, pip-audit over
  every locked dependency, and bandit's rules through ruff; Dependabot proposes updates
  weekly.

## Reporting a vulnerability

Please report it privately through GitHub's **Security → Report a vulnerability** on this
repository, not in a public issue. Include what you found, how to reproduce it, and what
it would let someone do. You will get an answer within a week.
