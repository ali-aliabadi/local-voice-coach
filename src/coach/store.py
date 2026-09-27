"""SQLite session store. stdlib sqlite3, no ORM, no migrations framework.

Two jobs: keep every turn you have ever practised, and remember how slow each backend
really was, so the picker shows measured latency instead of a guess.
"""

import sqlite3
import time

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    mode       TEXT NOT NULL,
    backend    TEXT NOT NULL,
    model      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
    id            INTEGER PRIMARY KEY,
    session_id    INTEGER NOT NULL REFERENCES sessions(id),
    at            TEXT NOT NULL,
    role          TEXT NOT NULL,          -- you | interviewer | review
    text          TEXT NOT NULL,
    wpm           INTEGER,
    fillers       INTEGER,
    pauses        INTEGER,
    longest_pause REAL,
    lead_in       REAL,
    stt_ms        REAL,
    reply_ms      REAL                    -- first token for streams, whole call otherwise
);
CREATE INDEX IF NOT EXISTS turns_session ON turns(session_id);
"""

_db: sqlite3.Connection | None = None
_session: int | None = None  # one session per process, so it lives here not in the contract


def db() -> sqlite3.Connection:
    global _db
    if _db is None:
        _db = sqlite3.connect(config.DB_PATH)
        _db.row_factory = sqlite3.Row
        _db.executescript(SCHEMA)
        _db.commit()
    return _db


def start(mode: str, backend: str, model: str) -> int:
    global _session
    cur = db().execute(
        "INSERT INTO sessions (started_at, mode, backend, model) VALUES (?, ?, ?, ?)",
        (time.strftime("%Y-%m-%d %H:%M:%S"), mode, backend, model),
    )
    db().commit()
    _session = cur.lastrowid
    return _session


def finish() -> None:
    if _session is None:
        return
    db().execute(
        "UPDATE sessions SET ended_at = ? WHERE id = ?",
        (time.strftime("%Y-%m-%d %H:%M:%S"), _session),
    )
    db().commit()


def record(
    role: str,
    text: str,
    metrics: dict | None = None,
    stt_ms: float | None = None,
    reply_ms: float | None = None,
) -> None:
    if _session is None:
        return
    m = metrics or {}
    db().execute(
        "INSERT INTO turns (session_id, at, role, text, wpm, fillers, pauses,"
        " longest_pause, lead_in, stt_ms, reply_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            _session,
            time.strftime("%Y-%m-%d %H:%M:%S"),
            role,
            text,
            m.get("wpm"),
            m.get("fillers"),
            m.get("pauses"),
            m.get("longest_pause"),
            m.get("lead_in"),
            stt_ms,
            reply_ms,
        ),
    )
    db().commit()


def measured_latency() -> dict[str, tuple[float, int]]:
    """{backend key: (mean ms, samples)} from every session ever run."""
    rows = (
        db()
        .execute(
            "SELECT s.backend AS backend, AVG(t.reply_ms) AS mean, COUNT(t.reply_ms) AS n "
            "FROM turns t JOIN sessions s ON s.id = t.session_id "
            "WHERE t.reply_ms IS NOT NULL GROUP BY s.backend"
        )
        .fetchall()
    )
    return {r["backend"]: (r["mean"], r["n"]) for r in rows}


def session_scores(session_id: int | None = None) -> list[dict]:
    rows = (
        db()
        .execute(
            "SELECT wpm, fillers, pauses, longest_pause, lead_in FROM turns "
            "WHERE session_id = ? AND role = 'you' AND wpm IS NOT NULL",
            (session_id or _session,),
        )
        .fetchall()
    )
    return [dict(r) for r in rows]


def trend(limit: int = 20) -> list[dict]:
    """Per-session averages, oldest first, so progress is visible."""
    rows = (
        db()
        .execute(
            "SELECT s.id, s.started_at, s.mode, s.backend, COUNT(t.id) AS answers,"
            " AVG(t.wpm) AS wpm, AVG(t.fillers) AS fillers, AVG(t.pauses) AS pauses,"
            " AVG(t.lead_in) AS lead_in "
            "FROM sessions s JOIN turns t ON t.session_id = s.id "
            "WHERE t.role = 'you' AND t.wpm IS NOT NULL "
            "GROUP BY s.id ORDER BY s.id DESC LIMIT ?",
            (limit,),
        )
        .fetchall()
    )
    return [dict(r) for r in reversed(rows)]
