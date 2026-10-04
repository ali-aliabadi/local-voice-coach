"""Reading back what you have done: one session, all sessions, and the trend.

Separate from store.py, which is about writing. These are the queries behind the review
and progress pages.
"""

import json

from . import store

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
    f"AVG({_when('t.lead_in')}) AS lead_in, "
    f"SUM({_MINUTES}) AS spoken"  # minutes of your own speech
)
# Start to last turn, in minutes. Not ended_at: a tab left open would count as practice.
LENGTH = (
    "(julianday((SELECT MAX(x.at) FROM turns x WHERE x.session_id = s.id))"
    " - julianday(s.started_at)) * 1440 AS minutes"
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


PAGE = 50


def sessions(before: int | None = None, limit: int = PAGE) -> list[dict]:
    """Sessions newest first, with their rates, a page at a time: `before` is the oldest id
    already shown. The list behind the history page."""
    rows = (
        store.db()
        .execute(
            "SELECT s.id, s.started_at, s.ended_at, s.mode, s.backend, s.model,"
            f"  s.goal_minutes, {LENGTH},"
            f"  COUNT(t.id) AS answers, {RATES}, SUM(t.wpm IS NOT NULL) AS scored "
            "FROM sessions s LEFT JOIN turns t ON t.session_id = s.id AND t.role = 'you' "
            "WHERE s.id < ? GROUP BY s.id HAVING answers > 0 ORDER BY s.id DESC LIMIT ?",
            (before or 2**62, limit),
        )
        .fetchall()
    )
    return [dict(r) for r in rows]


def detail(session_id: int) -> dict | None:
    """One session in full: every turn in order, with metrics and playable recordings."""
    head = (
        store.db()
        .execute(
            "SELECT s.id, s.started_at, s.ended_at, s.mode, s.backend, s.model, s.goal_minutes,"
            f" s.summary, {LENGTH} FROM sessions s WHERE s.id = ?",
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
            "  stt_ms, reply_ms, word_rows, notes, timing, audio_path IS NOT NULL AS has_audio "
            "FROM turns WHERE session_id = ? ORDER BY id",
            (session_id,),
        )
        .fetchall()
    )
    answers = [t for t in turns if t["role"] == "you" and t["wpm"] is not None]
    return {
        **dict(head),
        "summary": json.loads(head["summary"]) if head["summary"] else None,
        "listening": listening("", "", session_id),
        "turns": [_turn(t) for t in turns],
        "answers": len(answers),
        "averages": so_far(session_id),
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


def so_far(session_id: int) -> dict:
    """This session's rates across every answer so far."""
    return _rated(f"SELECT {RATES} FROM turns t WHERE t.session_id = ?", (session_id,))


def answers(session_id: int) -> list[dict]:
    """Each scored answer's rates in order: the session chart, one point per answer."""
    rows = store.db().execute(
        "SELECT words, wpm, fillers, pauses, lead_in FROM turns t"
        f" WHERE t.session_id = ? AND {RATED} ORDER BY t.id",
        (session_id,),
    )
    return [rates(dict(r)) for r in rows]


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


def listening(first_day: str, last_day: str, session_id: int | None = None) -> dict:
    """How many replies you needed help to follow - heard again, slower, or read - out of
    how many were tracked. Replies from before tracking began are left out rather than
    counted as followed: that would be a number nobody measured."""
    where = "session_id = ?" if session_id else "substr(at, 1, 10) BETWEEN ? AND ?"
    args = (session_id,) if session_id else (first_day, last_day)
    row = (
        store.db()
        .execute(
            "SELECT COUNT(helped) AS replies, COALESCE(SUM(helped != ''), 0) AS helped FROM turns"
            f" WHERE role NOT IN ('you', 'review') AND {where}",
            args,
        )
        .fetchone()
    )
    return dict(row)


def mistakes(days: int = 7) -> list[tuple[str, int]]:
    """The kinds of fix the coach made most over the last `days`, most frequent first: the
    patterns worth practising, as opposed to one-off slips."""
    rows = store.db().execute(
        "SELECT notes FROM turns WHERE role = 'you' AND notes IS NOT NULL"
        " AND at >= datetime('now', 'localtime', ?)",
        (f"-{days} days",),
    )
    counts: dict[str, int] = {}
    for row in rows:
        for fix in json.loads(row["notes"]).get("fixes") or []:
            kind = str(fix.get("kind") or "other")
            counts[kind] = counts.get(kind, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def trend(days: int = 366) -> list[dict]:
    """Rates per day, oldest first. A day is the unit of a daily habit, and it does not
    fall off the chart after a few weeks the way a per-session list capped at 60 did."""
    rows = (
        store.db()
        .execute(
            "SELECT substr(s.started_at, 1, 10) AS day, COUNT(DISTINCT s.id) AS sessions,"
            f"  COUNT(t.id) AS answers, {RATES} "
            "FROM sessions s JOIN turns t ON t.session_id = s.id "
            f"WHERE {RATED} GROUP BY day ORDER BY day DESC LIMIT ?",
            (days,),
        )
        .fetchall()
    )
    return [dict(r) for r in reversed(rows)]


def _turn(row) -> dict:
    turn = dict(row)
    turn["word_rows"] = json.loads(turn["word_rows"]) if turn["word_rows"] else []
    turn["notes"] = json.loads(turn["notes"]) if turn["notes"] else None
    turn["timing"] = json.loads(turn["timing"]) if turn["timing"] else None
    return rates(turn) if turn["role"] == "you" and turn["wpm"] is not None else turn
