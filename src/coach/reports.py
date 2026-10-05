"""What gets sent to your phone, and when.

The app only runs while you practise, so everything goes when a session ends - there is
no evening to remind you in, or Sunday to wait for. Each message is off unless Relay is
set up (relay.py) and its setting is on:
  - the session: a chart of each answer, what the page says beside it, then the study
    sheet or the coach's lessons
  - last week, after the first session since it ended: each day, against the week before

Each one remembers what it already sent, so a restart never sends it twice.
"""

import datetime as dt

from . import coach, history, picture, relay, settings, sheet, store


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


def _details(d: dict) -> str:
    """What the session page says beside the numbers: the chart cannot show any of it."""
    spoke = (d["averages"].get("spoken") or 0) / max(d["minutes"] or 1, 1)
    lines = [f"{d['mode']} · {d['answers']} answers · you spoke {round(spoke * 100)}% of it"]
    if d["previous"]:
        moved = picture.shifts(d["previous"], d["averages"])
        lines.append(
            f"Since last time: {', '.join(moved)}." if moved else "About the same as last time."
        )
    heard = d["listening"]
    if heard["replies"]:
        followed = heard["replies"] - heard["helped"]
        lines.append(f"You followed {followed} of {heard['replies']} replies by ear.")
    wait = sheet.waits(d)
    if wait:
        lines.append(f"Replies began {wait['total']:.1f}s after you stopped, on average.")
    return "\n".join(lines)


async def after_session(session_id: int) -> None:
    """Once the coach has finished with a session: its report, then last week's if that
    has not gone yet."""
    await coach.settled(session_id)
    if _on("relay_session_report"):
        await _session(session_id)
    if _on("relay_weekly"):
        await weekly()


async def _session(session_id: int) -> None:
    d = history.detail(session_id)
    if not d or not history.is_counted(session_id) or sent(session_id, d["answers"]):
        return
    minutes = round(d["minutes"] or 0)
    goal = f" of a {d['goal_minutes']} min goal" if d["goal_minutes"] else ""
    blocks = [relay.text(_details(d))]
    series = history.answers(session_id)
    if len(series) > 1:  # the chart carries the numbers: saying them again is noise
        chart = picture.panels(series, ["answer 1", f"answer {len(series)}"], d["averages"])
        caption = f"Each answer in order; the big number is the session. {picture.TREND}"
        blocks.append(relay.image(chart, caption))
    else:
        blocks.append(_numbers(d["averages"], d["previous"]))
    doc = sheet.render(session_id) if settings.get("relay_sheet") == "on" else None
    if doc is None:
        blocks += _lessons(d["summary"])  # the sheet carries them when there is one
    key = f"session-{session_id}-{d['answers']}"
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


def sent(session_id: int, answers: int) -> bool | None:
    """Whether the report on this session, as it stands, has gone; None if none would."""
    if not _on("relay_session_report"):
        return None
    return relay.recall(f"session:{session_id}") == str(answers)


def _period(first: str, last: str) -> dict:
    row = (
        store.db()
        .execute(
            f"SELECT {history.RATES} FROM turns t WHERE substr(t.at, 1, 10) BETWEEN ? AND ?"
            f" AND t.session_id IN {history.counted()}",
            (first, last),
        )
        .fetchone()
    )
    return dict(row) if row and row["wpm"] is not None else {}


async def weekly(now: dt.date | None = None) -> None:
    """Last week, Monday to Sunday: each day, against the week before."""
    now = now or dt.date.today()
    monday = now - dt.timedelta(days=now.weekday() + 7)
    week = monday.strftime("%G-W%V")
    if relay.recall("weekly") == week:
        return
    days = [(monday + dt.timedelta(days=n)).isoformat() for n in range(7)]
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
        (monday - dt.timedelta(days=7)).isoformat(), (monday - dt.timedelta(days=1)).isoformat()
    )
    spoken = sum(r["spoken"] or 0 for r in practised)
    blocks = [table]
    if len(practised) > 1:  # the chart carries the numbers, as after a session
        chart = picture.panels(practised, [days[0][5:], days[-1][5:]], this)
        blocks.append(relay.image(chart, f"Each day; the big number is the week. {picture.TREND}"))
    else:
        blocks.append(_numbers(this, last))
    repeats = history.mistakes(7)
    if repeats and settings.get("relay_lessons") == "on":
        top = ", ".join(f"{kind} ({n})" for kind, n in repeats[:4])
        blocks.append(relay.text(f"What the coach corrected most in the last 7 days: {top}."))
    await relay.send(
        f"Last week: {len(practised)} day{'s' if len(practised) != 1 else ''}, "
        f"{spoken:.0f} min of speaking",
        blocks,
        key=f"weekly-{week}",
    )
