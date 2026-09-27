"""SQLite session store. stdlib sqlite3, no ORM, no migrations framework.

Two jobs: keep every turn you have ever practised, and remember how slow each backend
really was, so the picker shows measured latency instead of a guess.
"""

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
    reply_ms      REAL,                   -- first token for streams, whole call otherwise
    audio_path    TEXT                    -- recording on disk, or NULL once purged
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
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
    audio_path: str | None = None,
) -> int | None:
    """Persist one turn. Returns its id, which the browser uses to fetch the recording."""
    if _session is None:
        return None
    m = metrics or {}
    cursor = db().execute(
        "INSERT INTO turns (session_id, at, role, text, wpm, fillers, pauses,"
        " longest_pause, lead_in, stt_ms, reply_ms, audio_path)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
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
            audio_path,
        ),
    )
    db().commit()
    return cursor.lastrowid


def current_session() -> int | None:
    return _session


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
