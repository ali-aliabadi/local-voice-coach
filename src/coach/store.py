"""SQLite session store. stdlib sqlite3, no ORM, no migrations framework.

Two jobs: keep every turn you have ever practised, and remember how slow each backend
really was, so the picker shows measured latency instead of a guess.
"""

import json
import pathlib
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
    model      TEXT NOT NULL,
    goal_minutes INTEGER,               -- what the user set out to do, or NULL
    summary    TEXT                     -- the coach's summary, JSON
);
CREATE TABLE IF NOT EXISTS turns (
    id            INTEGER PRIMARY KEY,
    session_id    INTEGER NOT NULL REFERENCES sessions(id),
    at            TEXT NOT NULL,
    role          TEXT NOT NULL,          -- you | interviewer | review
    text          TEXT NOT NULL,
    words         INTEGER,
    wpm           INTEGER,
    fillers       INTEGER,
    pauses        INTEGER,
    longest_pause REAL,
    lead_in       REAL,
    stt_ms        REAL,
    reply_ms      REAL,                   -- first token for streams, whole call otherwise
    audio_path    TEXT,                   -- recording on disk, or NULL once purged
    word_rows     TEXT,                   -- per-word timings, so a past answer can still
                                          -- show its highlighted transcript and timeline
    notes         TEXT,                   -- the coach's notes on an answer, JSON
    helped        TEXT,                   -- on a reply: what the user needed to follow it,
                                          -- "again,text"; "" by ear; NULL never tracked
    timing        TEXT                    -- on a reply: ms from the end of the answer to
                                          -- its first sound, and where that went, JSON
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS turns_session ON turns(session_id);
"""

_db: sqlite3.Connection | None = None


# Columns added after the first release. CREATE TABLE IF NOT EXISTS will not add them to
# a database that already exists, so they are applied here instead.
ADDED_COLUMNS = {
    "turns": {
        "words": "INTEGER",
        "word_rows": "TEXT",
        "notes": "TEXT",
        "helped": "TEXT",
        "timing": "TEXT",
    },
    "sessions": {"goal_minutes": "INTEGER", "summary": "TEXT"},
}


def _migrate(connection: sqlite3.Connection) -> None:
    for table, columns in ADDED_COLUMNS.items():
        present = {r["name"] for r in connection.execute(f"PRAGMA table_info({table})")}
        for name, kind in columns.items():
            if name not in present:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
    connection.commit()


def db() -> sqlite3.Connection:
    global _db
    if _db is None:
        _db = sqlite3.connect(config.DB_PATH)
        _db.row_factory = sqlite3.Row
        _db.executescript(SCHEMA)
        _db.commit()
        _migrate(_db)
    return _db


# Session ids are passed in, never held here: two tabs each own a session, and a global
# "current session" filed one tab's answers under the other's.
def start(mode: str, backend: str, model: str, goal: int | None = None) -> int:
    cur = db().execute(
        "INSERT INTO sessions (started_at, mode, backend, model, goal_minutes)"
        " VALUES (?, ?, ?, ?, ?)",
        (time.strftime("%Y-%m-%d %H:%M:%S"), mode, backend, model, goal or None),
    )
    db().commit()
    return cur.lastrowid


def elapsed(session_id: int) -> float:
    """Seconds since the session started, so a reloaded page keeps counting from there."""
    row = db().execute("SELECT started_at FROM sessions WHERE id = ?", (session_id,)).fetchone()
    started = time.mktime(time.strptime(row["started_at"], "%Y-%m-%d %H:%M:%S"))
    return time.time() - started


def goal(session_id: int) -> int | None:
    row = db().execute("SELECT goal_minutes FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return row["goal_minutes"] if row else None


def resume(session_id: int) -> int | None:
    """Re-attach to an existing session, so a browser refresh does not orphan it."""
    row = db().execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return row["id"] if row else None


def conversation(session_id: int, limit: int = 16) -> list[dict]:
    """The turns of a session as chat messages, oldest first.

    Used to rebuild an interviewer's memory after a refresh: the browser reconnects and
    the conversation carries on instead of starting over.
    """
    rows = (
        db()
        .execute(
            "SELECT role, text FROM turns WHERE session_id = ? AND role != 'review'"
            " ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
        .fetchall()
    )
    return [
        {"role": "user" if r["role"] == "you" else "assistant", "content": r["text"]}
        for r in reversed(rows)
    ]


def finish(session_id: int) -> None:
    db().execute(
        "UPDATE sessions SET ended_at = ? WHERE id = ?",
        (time.strftime("%Y-%m-%d %H:%M:%S"), session_id),
    )
    db().commit()


def record(
    session_id: int,
    role: str,
    text: str,
    metrics: dict | None = None,
    stt_ms: float | None = None,
    reply_ms: float | None = None,
    audio_path: str | None = None,
    word_rows: list[dict] | None = None,
    timing: dict | None = None,
) -> int | None:
    """Persist one turn. Returns its id, which the browser uses to fetch the recording."""
    m = metrics or {}
    cursor = db().execute(
        "INSERT INTO turns (session_id, at, role, text, words, wpm, fillers, pauses,"
        " longest_pause, lead_in, stt_ms, reply_ms, audio_path, word_rows, timing)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            session_id,
            time.strftime("%Y-%m-%d %H:%M:%S"),
            role,
            text,
            m.get("words"),
            m.get("wpm"),
            m.get("fillers"),
            m.get("pauses"),
            m.get("longest_pause"),
            m.get("lead_in"),
            stt_ms,
            reply_ms,
            audio_path,
            json.dumps(word_rows) if word_rows else None,
            json.dumps(timing) if timing else None,
        ),
    )
    db().commit()
    return cursor.lastrowid


def last_said(session_id: int) -> str:
    """What the partner said last: the thing an answer is replying to."""
    row = (
        db()
        .execute(
            "SELECT text FROM turns WHERE session_id = ? AND role NOT IN ('you', 'review')"
            " ORDER BY id DESC LIMIT 1",
            (session_id,),
        )
        .fetchone()
    )
    return row["text"] if row else ""


def helped(turn_id: int, kinds: list[str]) -> None:
    """Mark a reply as one the user needed help to follow: heard again, slower, or read."""
    db().execute("UPDATE turns SET helped = ? WHERE id = ?", (",".join(sorted(kinds)), turn_id))
    db().commit()


def audio_path(turn_id: int) -> str | None:
    row = db().execute("SELECT audio_path FROM turns WHERE id = ?", (turn_id,)).fetchone()
    return row["audio_path"] if row else None


def purge_audio(older_than_days: int) -> int:
    """Delete recordings past retention. 0 means keep forever. Returns how many went."""
    if older_than_days <= 0:
        return 0
    cutoff = time.time() - older_than_days * 86400
    gone = 0
    for row in (
        db().execute("SELECT id, audio_path FROM turns WHERE audio_path IS NOT NULL").fetchall()
    ):
        path = pathlib.Path(row["audio_path"])
        if not path.exists() or path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            db().execute("UPDATE turns SET audio_path = NULL WHERE id = ?", (row["id"],))
            gone += 1
    db().commit()
    return gone


def forget_everything() -> None:
    """The delete button. The pitch is that this data is yours, so leaving is one click."""
    for row in db().execute("SELECT audio_path FROM turns WHERE audio_path IS NOT NULL").fetchall():
        pathlib.Path(row["audio_path"]).unlink(missing_ok=True)
    db().executescript("DELETE FROM turns; DELETE FROM sessions;")
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


def session_scores(session_id: int) -> list[dict]:
    rows = (
        db()
        .execute(
            "SELECT wpm, fillers, pauses, longest_pause, lead_in FROM turns "
            "WHERE session_id = ? AND role = 'you' AND wpm IS NOT NULL",
            (session_id,),
        )
        .fetchall()
    )
    return [dict(r) for r in rows]
