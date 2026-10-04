"""What gets sent to your phone, and when.

Three messages, each off unless Relay is set up (relay.py) and its setting is on:
  - after a session: the numbers, a chart of each answer, and the coach's lessons
  - a daily reminder if you have not practised by your chosen time, with buttons
  - a weekly report on Sunday evening: each day, against the week before

Each one remembers what it already sent, so a restart never sends it twice.
"""

import asyncio
import datetime as dt
import time

from . import coach, history, picture, relay, settings, sheet, store, today

NOW, LATER, SKIP = "Starting now", "In 30 min", "Skip today"
WEEKLY_DAY, WEEKLY_HOUR = 6, 20  # Sunday, from 20:00


def _on(key: str) -> bool:
    return relay.enabled() and settings.get(key) == "on"


def _numbers(now: dict, before: dict) -> dict:
    """The four numbers as Relay fields, each against the time before when there was one."""
    items = []
    for key, (label, _, _) in picture.SERIES.items():
        value = now.get(key)
        if value is None:
            continue
        shown = f"{value:.0f}" if key == "wpm" else f"{value:.1f}"
        if before.get(key) is not None:
            shown += f" (was {before[key]:.0f})" if key == "wpm" else f" (was {before[key]:.1f})"
        items.append({"label": label, "value": shown})
    return {"type": "fields", "items": items}


def _lessons(summary: dict | None) -> list[dict]:
    """The coach's summary as text. Off when you would rather keep your sentences off
    Telegram: the lessons quote them."""
    if not summary or settings.get("relay_lessons") != "on":
        return []
    parts = []
    if summary.get("work_on"):
        parts.append("Work on next:\n" + "\n".join(f"• {w}" for w in summary["work_on"]))
    if summary.get("phrases"):
        parts.append(
            "Phrases worth learning:\n"
            + "\n".join(f"• {p.get('phrase')}: {p.get('meaning')}" for p in summary["phrases"])
        )
    if summary.get("instead_of_um"):
        parts.append('Instead of "um", try: ' + " / ".join(summary["instead_of_um"]))
    return [relay.text("\n\n".join(parts))] if parts else []


async def after_session(session_id: int, again: bool = False) -> None:
    """Report a session once the coach has finished with it. `again` is the session
    page's "Send to Telegram": sent even if it went before, and whatever the setting."""
    if not (relay.enabled() if again else _on("relay_session_report")):
        return
    await coach.settled(session_id)
    d = history.detail(session_id)
    reported = relay.recall(f"session:{session_id}") == str(d["answers"]) if d else False
    if not d or not d["answers"] or (reported and not again):
        return
    minutes = round(d["minutes"] or 0)
    goal = f" of a {d['goal_minutes']} min goal" if d["goal_minutes"] else ""
    spoke = (d["averages"].get("spoken") or 0) / max(d["minutes"] or 1, 1)
    blocks = [
        relay.text(f"{d['mode']} · {d['answers']} answers · you spoke {round(spoke * 100)}%"),
        _numbers(d["averages"], d["previous"]),
    ]
    series = history.answers(session_id)
    if len(series) > 1:
        labels = ["answer 1", f"answer {len(series)}"]
        chart = picture.panels(series, labels, d["averages"])
        blocks.append(relay.image(chart, "Each answer in order; the big number is the session"))
    doc = sheet.render(session_id) if settings.get("relay_sheet") == "on" else None
    if doc is None:
        blocks += _lessons(d["summary"])  # the sheet carries them when there is one
    # The same key makes Relay hand back the first message instead of sending twice, so a
    # deliberate resend needs a key of its own.
    key = f"session-{session_id}-{d['answers']}" + (f"-{int(time.time())}" if again else "")
    await relay.send(f"Session done: {minutes} min{goal}", blocks, key=key)
    if doc:
        await _send_sheet(doc, d["started_at"][:10], key)
    relay.remember(f"session:{session_id}", str(d["answers"]))


async def _send_sheet(doc, day: str, key: str) -> None:
    """The study sheet as a PDF - a line saying what it is, then the file, as Relay's
    recipe has it. As its pages, one image each, on a Relay from before file blocks."""
    pdf = doc.pdf()
    title = "Your study sheet"
    if len(pdf) > relay.FILE_LIMIT:  # too big to attach: say where it is instead
        where = relay.text("Too large to attach - open it from the session page in the app.")
        await relay.send(title, [where], key=f"{key}-sheet")
        return
    what = relay.text(
        "The fixes worth the most, phrases for your conversations, what to practise "
        "tomorrow, and how the session went - to keep and read again."
    )
    sheet_file = relay.file(pdf, f"study-sheet-{day}.pdf", "application/pdf", title)
    try:
        await relay.send(title, [what, sheet_file], key=f"{key}-sheet")
        return
    except RuntimeError as exc:
        if not str(exc).startswith(("relay 400", "relay 422")):
            raise
    pages = doc.pngs()
    for n, page in enumerate(pages, 1):
        title = f"Study sheet, page {n} of {len(pages)}"
        await relay.send(title, [relay.image(page, title)], key=f"{key}-sheet-{n}")


def after_session_later(session_id: int, again: bool = False) -> None:
    async def safely():
        try:
            await after_session(session_id, again)
        except Exception as exc:  # a report must never break anything
            print(f"  relay: {exc}")

    asyncio.create_task(safely())


async def remind(now: dt.datetime | None = None) -> None:
    """If you have not practised by your reminder time, ask - once, unless you snooze it."""
    at = str(settings.get("remind_at")).strip()
    if not relay.enabled() or not at:
        return
    now = now or dt.datetime.now()
    day = now.date().isoformat()
    if today.days_practised()[:1] == [day] or relay.recall("remind:done") == day:
        return
    asked = relay.recall("remind:asked")
    if asked.startswith(day):  # waiting on an answer: read it, never nag
        choice = await relay.answer(asked.split("|", 1)[1])
        if not choice:
            return
        relay.remember("remind:asked", "")
        if choice != LATER:
            relay.remember("remind:done", day)
            return
        relay.remember("remind:next", (now + dt.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M"))
        return
    due = f"{day}T{at}"
    snoozed = relay.recall("remind:next")
    if snoozed.startswith(day):
        due = max(due, snoozed)
    if now.strftime("%Y-%m-%dT%H:%M") < due:
        return
    days = today.streak(now.date())
    line = (
        f"{days} day{'s' if days != 1 else ''} in a row so far. Today keeps it going."
        if days
        else "A short session still counts."
    )
    question = {"type": "question", "text": "Practise now?", "options": [NOW, LATER, SKIP]}
    message = await relay.send(
        "No practice yet today", [relay.text(line), question], key=f"remind-{day}-{now:%H%M}"
    )
    relay.remember("remind:asked", f"{day}|{message}")
    relay.remember("remind:next", "")


def _period(first: str, last: str) -> dict:
    row = (
        store.db()
        .execute(
            f"SELECT {history.RATES} FROM turns t WHERE substr(t.at, 1, 10) BETWEEN ? AND ?",
            (first, last),
        )
        .fetchone()
    )
    return dict(row) if row and row["wpm"] is not None else {}


async def weekly(now: dt.datetime | None = None) -> None:
    """Sunday evening: each day of the week, against the week before."""
    now = now or dt.datetime.now()
    week = now.strftime("%G-W%V")
    if not _on("relay_weekly") or now.weekday() != WEEKLY_DAY or now.hour < WEEKLY_HOUR:
        return
    if relay.recall("weekly") == week:
        return
    days = [(now.date() - dt.timedelta(days=n)).isoformat() for n in range(6, -1, -1)]
    by_day = {r["day"]: r for r in history.trend(14)}
    practised = [by_day[d] for d in days if d in by_day]
    relay.remember("weekly", week)
    if not practised:
        return
    table = {
        "type": "table",
        "columns": ["Day", "Min", "Fillers", "Pauses"],
        "rows": [
            [
                d[5:],
                f"{by_day[d]['spoken']:.0f}",
                f"{by_day[d]['fillers']:.1f}",
                f"{by_day[d]['pauses']:.1f}",
            ]
            if d in by_day
            else [d[5:], "-", "-", "-"]
            for d in days
        ],  # fmt: skip
    }
    this = _period(days[0], days[-1])
    last = _period(
        (now.date() - dt.timedelta(days=13)).isoformat(),
        (now.date() - dt.timedelta(days=7)).isoformat(),
    )
    spoken = sum(r["spoken"] or 0 for r in practised)
    blocks = [table, _numbers(this, last)]
    chart = picture.panels(practised, [days[0][5:], days[-1][5:]], this)
    blocks.append(relay.image(chart, "Each day; the big number is the week"))
    repeats = history.mistakes(7)
    if repeats and settings.get("relay_lessons") == "on":
        top = ", ".join(f"{kind} ({n})" for kind, n in repeats[:4])
        blocks.append(relay.text(f"What the coach corrected most this week: {top}."))
    await relay.send(
        f"Your week: {len(practised)} day{'s' if len(practised) != 1 else ''}, "
        f"{spoken:.0f} min of speaking",
        blocks,
        key=f"weekly-{week}",
    )
