"""Where you stand today, for the home page.

How long you have practised today, how many days in a row, and what the coach said to
work on last time - the three things worth knowing before you start.
"""

import datetime as dt
import json

from . import history, store


def days_practised() -> list[str]:
    """Every day with a session that counts, newest first."""
    rows = store.db().execute(
        "SELECT DISTINCT substr(at, 1, 10) AS day FROM turns WHERE role = 'you'"
        f" AND session_id IN {history.counted()} ORDER BY day DESC"
    )
    return [r["day"] for r in rows]


def streak(today: dt.date) -> int:
    """Days in a row with practice, counting back from today, or from yesterday if today
    has not happened yet."""
    days = set(days_practised())
    day = today if today.isoformat() in days else today - dt.timedelta(days=1)
    count = 0
    while day.isoformat() in days:
        count += 1
        day -= dt.timedelta(days=1)
    return count


def summary(today: dt.date) -> dict:
    day = today.isoformat()
    sessions = [s for s in history.sessions(limit=20) if s["started_at"].startswith(day)]
    latest = history.sessions(limit=1)
    coached = (
        store.db()
        .execute("SELECT summary FROM sessions WHERE summary IS NOT NULL ORDER BY id DESC LIMIT 1")
        .fetchone()
    )
    advice = json.loads(coached["summary"]) if coached else {}
    return {
        "minutes": sum(s["minutes"] or 0 for s in sessions),
        "spoken": sum(s["spoken"] or 0 for s in sessions),
        "sessions": len(sessions),
        "streak": streak(today),
        "last": latest[0] if latest else None,
        "work_on": advice.get("work_on") or [],
        "phrases": advice.get("phrases") or [],
    }
