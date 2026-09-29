"""Reading back what you have done: one session, all sessions, and the trend.

Separate from store.py, which is about writing. These are the queries behind the review
and progress pages.
"""

import json

from . import store

# Interviewer turns are stored per-panellist ("panel:MAYA"), so match on a prefix.
SPOKE = "(t.role = 'interviewer' OR t.role LIKE 'panel:%')"


def sessions(limit: int = 50) -> list[dict]:
    """Every session, newest first, with its averages. The list behind the history page."""
    rows = (
        store.db()
        .execute(
            "SELECT s.id, s.started_at, s.ended_at, s.mode, s.backend, s.model,"
            "  COUNT(t.id) AS answers, AVG(t.wpm) AS wpm, AVG(t.fillers) AS fillers,"
            "  AVG(t.pauses) AS pauses, AVG(t.lead_in) AS lead_in,"
            "  SUM(t.wpm IS NOT NULL) AS scored "
            "FROM sessions s LEFT JOIN turns t ON t.session_id = s.id AND t.role = 'you' "
            "GROUP BY s.id HAVING answers > 0 ORDER BY s.id DESC LIMIT ?",
            (limit,),
        )
        .fetchall()
    )
    return [dict(r) for r in rows]


def detail(session_id: int) -> dict | None:
    """One session in full: every turn in order, with metrics and playable recordings."""
    head = (
        store.db()
        .execute(
            "SELECT id, started_at, ended_at, mode, backend, model FROM sessions WHERE id = ?",
            (session_id,),
        )
        .fetchone()
    )
    if head is None:
        return None
    turns = (
        store.db()
        .execute(
            "SELECT id, at, role, text, wpm, fillers, pauses, longest_pause, lead_in,"
            "  stt_ms, reply_ms, word_rows, audio_path IS NOT NULL AS has_audio "
            "FROM turns WHERE session_id = ? ORDER BY id",
            (session_id,),
        )
        .fetchall()
    )
    answers = [dict(t) for t in turns if t["role"] == "you" and t["wpm"] is not None]
    return {
        **dict(head),
        "turns": [_turn(t) for t in turns],
        "answers": len(answers),
        "averages": _average(answers),
    }


def totals() -> dict:
    """Lifetime numbers for the progress page."""
    row = (
        store.db()
        .execute(
            "SELECT COUNT(DISTINCT s.id) AS sessions, COUNT(t.id) AS answers,"
            "  AVG(t.wpm) AS wpm, AVG(t.fillers) AS fillers, AVG(t.pauses) AS pauses,"
            "  AVG(t.lead_in) AS lead_in, SUM(t.words) AS words "
            "FROM turns t JOIN sessions s ON s.id = t.session_id "
            "WHERE t.role = 'you' AND t.wpm IS NOT NULL"
        )
        .fetchone()
    )
    out = dict(row) if row else {}
    return {k: (v if v is not None else 0) for k, v in out.items()}


def recent(limit: int = 5) -> dict:
    """Averages over the last few sessions, for the interviewer's pacing note."""
    row = (
        store.db()
        .execute(
            "SELECT COUNT(*) AS answers, AVG(wpm) AS wpm, AVG(fillers) AS fillers,"
            "  AVG(pauses) AS pauses, AVG(lead_in) AS lead_in FROM turns "
            "WHERE role = 'you' AND wpm IS NOT NULL AND session_id IN "
            "  (SELECT id FROM sessions ORDER BY id DESC LIMIT ?)",
            (limit,),
        )
        .fetchone()
    )
    if not row or not row["answers"]:
        return {}
    return dict(row)


def _turn(row) -> dict:
    turn = dict(row)
    turn["word_rows"] = json.loads(turn["word_rows"]) if turn["word_rows"] else []
    return turn


def _average(answers: list[dict]) -> dict:
    if not answers:
        return {}
    keys = ("wpm", "fillers", "pauses", "lead_in")
    return {k: sum(a[k] for a in answers) / len(answers) for k in keys}
