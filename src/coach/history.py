"""Reading back what you have done: one session, all sessions, and the trend.

Separate from store.py, which is about writing. These are the queries behind the review
and progress pages.
"""

import json

from . import store

# Interviewer turns are stored per-panellist ("panel:MAYA"), so match on a prefix.
SPOKE = "(t.role = 'interviewer' OR t.role LIKE 'panel:%')"

# Rates, not counts. A long answer holds more fillers without being any worse, and talk
# mode deliberately asks for long answers, so per-answer counts would chart improvement
# as decline. Fillers are per 100 words, pauses per minute of speech, and everything is
# weighted by words so one ten-word answer cannot swing a session. Defined once, here,
# and usable in any query over `turns t`: non-answers and unscored answers drop out.
RATED = "t.role = 'you' AND t.wpm > 0 AND t.words > 0"


def _when(expression: str) -> str:
    return f"CASE WHEN {RATED} THEN {expression} END"


_MINUTES = _when("t.words * 1.0 / t.wpm")
RATES = (
    f"SUM({_when('t.words')}) / SUM({_MINUTES}) AS wpm, "
    f"100.0 * SUM({_when('t.fillers')}) / SUM({_when('t.words')}) AS fillers, "
    f"SUM({_when('t.pauses')}) / SUM({_MINUTES}) AS pauses, "
    f"AVG({_when('t.lead_in')}) AS lead_in"
)


def rates(m: dict | None) -> dict | None:
    """One answer's counts as rates, the same way RATES treats many."""
    if not m:
        return m
    words, wpm = m.get("words") or 0, m.get("wpm") or 0
    return {
        **m,
        "fillers": 100 * (m.get("fillers") or 0) / words if words else 0.0,
        "pauses": (m.get("pauses") or 0) * wpm / words if words and wpm else 0.0,
    }


def sessions(limit: int = 50) -> list[dict]:
    """Every session, newest first, with its averages. The list behind the history page."""
    rows = (
        store.db()
        .execute(
            "SELECT s.id, s.started_at, s.ended_at, s.mode, s.backend, s.model,"
            f"  COUNT(t.id) AS answers, {RATES}, SUM(t.wpm IS NOT NULL) AS scored "
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
            "SELECT id, at, role, text, words, wpm, fillers, pauses, longest_pause, lead_in,"
            "  stt_ms, reply_ms, word_rows, audio_path IS NOT NULL AS has_audio "
            "FROM turns WHERE session_id = ? ORDER BY id",
            (session_id,),
        )
        .fetchall()
    )
    answers = [t for t in turns if t["role"] == "you" and t["wpm"] is not None]
    return {
        **dict(head),
        "turns": [_turn(t) for t in turns],
        "answers": len(answers),
        "averages": _rated(f"SELECT {RATES} FROM turns t WHERE t.session_id = ?", (session_id,)),
        # What to measure this session against: the one before it, and your own running
        # average. A number with nothing to compare it to says nothing.
        "previous": previous(session_id),
        "lifetime": {k: v for k, v in totals().items() if k in _KEYS},
    }


_KEYS = ("wpm", "fillers", "pauses", "lead_in")


def previous(before: int) -> dict:
    """Averages of the session before this one, so a review can say what changed."""
    return _rated(
        f"SELECT {RATES} FROM turns t WHERE t.session_id = (SELECT MAX(s.id) FROM sessions s"
        "  JOIN turns x ON x.session_id = s.id AND x.role = 'you' AND x.wpm > 0 WHERE s.id < ?)",
        (before,),
    )


def _rated(sql: str, args: tuple) -> dict:
    """One row of RATES as a dict, or {} when nothing in it was rated."""
    row = store.db().execute(sql, args).fetchone()
    return dict(row) if row and row["wpm"] is not None else {}


def totals() -> dict:
    """Lifetime numbers for the progress page."""
    row = (
        store.db()
        .execute(
            "SELECT COUNT(DISTINCT s.id) AS sessions, COUNT(t.id) AS answers,"
            f"  {RATES}, SUM(t.words) AS words "
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
            f"SELECT COUNT(*) AS answers, {RATES} FROM turns t "
            f"WHERE {RATED} AND t.session_id IN "
            "  (SELECT id FROM sessions ORDER BY id DESC LIMIT ?)",
            (limit,),
        )
        .fetchone()
    )
    if not row or not row["answers"]:
        return {}
    return dict(row)


def trend(limit: int = 60) -> list[dict]:
    """Per-session rates, oldest first, so progress is visible."""
    rows = (
        store.db()
        .execute(
            f"SELECT s.id, s.started_at, s.mode, s.backend, COUNT(t.id) AS answers, {RATES} "
            "FROM sessions s JOIN turns t ON t.session_id = s.id "
            f"WHERE {RATED} GROUP BY s.id ORDER BY s.id DESC LIMIT ?",
            (limit,),
        )
        .fetchall()
    )
    return [dict(r) for r in reversed(rows)]


def _turn(row) -> dict:
    turn = dict(row)
    turn["word_rows"] = json.loads(turn["word_rows"]) if turn["word_rows"] else []
    return rates(turn) if turn["role"] == "you" and turn["wpm"] is not None else turn
