"""The study sheet: a page or two written by a model after the session, to keep.

The coach's notes are per answer and live in the app. The sheet is the take-away: what
went well, the fixes worth the most, phrases for the conversations you actually have -
each shown where it would have fitted - what to say instead of "um", and three small
things to practise tomorrow. A PDF to download or print, and images on Telegram.
"""

import datetime as dt
import json

from . import backends, coach, history, layout, llm, picture, profile, settings, store

SHEET_PROMPT = (
    "You are a warm, experienced English coach. Below is a whole spoken practice session: "
    "the conversation, transcribed by speech recognition, with the notes already written on "
    "each of the learner's answers, and their delivery numbers. Write their study sheet - the "
    "page they keep and read again tomorrow. Make it specific to what they actually said, "
    "genuinely useful, and encouraging: the few things worth the most, never every slip. "
    "Speak to them as 'you'. Never blame them for what speech recognition misheard or how "
    "it spelled things, and never mention um, pauses or hesitation outside instead_of_um.\n"
    "A fix must keep what they meant. If you cannot tell what they meant - the words may "
    "have been misheard - leave it out rather than guess. Every phrase must be one native "
    "speakers really use, and its example must use it correctly.\n\n"
    "Reply with JSON only:\n"
    '{"title": "a short, warm headline for this session, under 10 words", '
    '"went_well": "2-3 sentences on what went well, quoting them", '
    '"fixes": [up to 5 {"said": "their words", "better": "the natural version", '
    '"why": "a few words"}, recurring patterns first], '
    '"phrases": [6 to 8 {"phrase": "...", "meaning": "...", "instead_of": "their words it '
    'could replace, or empty", "example": "a sentence they could say about the things they '
    'talked about"}], '
    '"instead_of_um": [3 short phrases to buy thinking time, suited to how they talk], '
    '"practice": [3 small, concrete exercises for tomorrow, one sentence each - e.g. retell '
    "a story from this session in 60 seconds using two of the phrases]}"
)
MIN_ANSWERS = 3  # fewer, and there is not enough to write a sheet about
SHEET_TOKENS = 8000  # a thinking model spends much of it before writing a word


def endpoint() -> llm.Endpoint | None:
    backend = backends.BY_KEY.get(settings.get("sheet_backend"))
    return llm.endpoint_for(backend) if backend else None


async def write(session_id: int) -> None:
    """Write the sheet, once the coach's summary and notes are in."""
    await coach.settled(session_id)
    ep = endpoint()
    d = history.detail(session_id)
    if not ep or not d or d["answers"] < MIN_ANSWERS:
        return
    lines = []
    for turn in d["turns"]:
        lines.append(f"{'LEARNER' if turn['role'] == 'you' else 'PARTNER'}: {turn['text']}")
        if turn.get("notes"):
            lines.append(f"  notes: {json.dumps(turn['notes'])}")
    numbers = ", ".join(f"{k} {v:.1f}" for k, v in d["averages"].items() if v is not None)
    first = profile.get("native_language").strip()
    system = SHEET_PROMPT + (f"\n\nTheir first language is {first}." if first else "")
    reply = await llm.patiently(
        ep,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": "\n".join(lines) + f"\n\nDelivery: {numbers}"},
        ],
        max_tokens=SHEET_TOKENS,
    )
    found = coach.parse(reply.text)
    if found:
        store.db().execute(
            "UPDATE sessions SET sheet = ? WHERE id = ?", (json.dumps(found), session_id)
        )
        store.db().commit()


def later(session_id: int) -> None:
    """Write it in the background, counted with the coach's work for this session."""
    if endpoint() and history.is_counted(session_id):
        coach.later(session_id, write(session_id))


def stored(session_id: int) -> dict | None:
    row = store.db().execute("SELECT sheet FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return json.loads(row["sheet"]) if row and row["sheet"] else None


def _tiles(averages: dict) -> list[tuple[str, str, str, bool]]:
    tiles = []
    for key, (label, _, (lo, hi)) in picture.SERIES.items():
        value = averages.get(key)
        if value is None:
            continue
        shown = f"{value:.0f}" if key == "wpm" else f"{value:.1f}"
        target = f"{lo:g}-{hi:g}" if key == "wpm" else f"{hi:g} or less"
        tiles.append((shown, label, f"target {target}", lo <= value <= hi))
    return tiles


def _time_tiles(d: dict) -> list[tuple[str, str, str, bool | None]]:
    """How the session's time went: its length against the goal, how much of it was you,
    how fast replies came, how many you followed by ear. Only what was measured."""
    tiles = []
    minutes, goal = d.get("minutes") or 0, d.get("goal_minutes")
    if minutes:
        note = (
            (f"goal {goal} min, reached" if minutes >= goal else f"goal was {goal} min")
            if goal
            else "start to last answer"
        )
        tiles.append((f"{round(minutes)} min", "session", note, minutes >= goal if goal else None))
    spoken = (d.get("averages") or {}).get("spoken")
    if spoken and minutes:
        shown = f"{spoken:.0f} min" if spoken >= 1 else "<1 min"
        tiles.append(
            (shown, "you speaking", f"{round(spoken / minutes * 100)}% of the session", None)
        )
    wait = waits(d)
    if wait:
        tiles.append((f"{wait['total']:.1f}s", "until a reply began", "after you stopped", None))
    heard = d.get("listening") or {}
    if heard.get("replies"):
        followed = heard["replies"] - heard["helped"]
        tiles.append(
            (f"{followed}/{heard['replies']}", "replies followed by ear", "no replay or text", None)
        )
    return tiles


def waits(d: dict) -> dict | None:
    """The average reply wait and where it went, over the replies that were timed."""
    timed = [t["timing"] for t in d["turns"] if (t.get("timing") or {}).get("total")]
    if not timed:
        return None
    return {k: sum(t.get(k, 0) for t in timed) / len(timed) / 1000 for k in timed[0]}


def _charts(doc: layout.Doc, session_id: int, d: dict) -> None:
    """The session answer by answer, and the last fortnight day by day, on the app's
    fixed scales - a flat stretch has to look flat."""
    series, days = history.answers(session_id), history.trend(14)
    if len(series) < 2 and len(days) < 2:
        return
    doc.heading("In charts")
    if len(series) > 1:
        chart = picture.panels(series, ["answer 1", f"answer {len(series)}"], d["averages"])
        doc.image(chart, "This session, one point per answer. The shaded band is the target; the "
                  f"big number is the whole session. {picture.TREND}")  # fmt: skip
    if len(days) > 1:
        chart = picture.panels(days, [days[0]["day"][5:], days[-1]["day"][5:]], days[-1])
        doc.image(chart, f"Your last {len(days)} days of practice, up to today, one point per "
                  f"day. The big number is the latest day. {picture.TREND}")  # fmt: skip


def render(session_id: int) -> layout.Doc | None:
    s, d = stored(session_id), history.detail(session_id)
    if not s or not d:
        return None
    day = dt.datetime.strptime(d["started_at"][:10], "%Y-%m-%d").strftime("%-d %B %Y")
    doc = layout.Doc(footer=f"Study sheet · {day}")
    _head(doc, s, d, day)
    _fixes(doc, s.get("fixes") or [])
    _phrases(doc, s.get("phrases") or [])
    _lists(doc, s)
    _charts(doc, session_id, d)
    return doc


def _head(doc: layout.Doc, s: dict, d: dict, day: str) -> None:
    """The headline, what went well, the numbers, and where the time went."""
    minutes = f" · {round(d['minutes'])} min" if d.get("minutes") else ""
    doc.text(f"STUDY SHEET · {d['mode'].upper()} · {day.upper()}{minutes}", 20, color=picture.MUTED)
    doc.text(s.get("title") or "Your session", 46, bold=True, after=18)
    if s.get("went_well"):
        doc.text(s["went_well"], 27, color=layout.GOOD, after=26)
    doc.tiles(_tiles(d["averages"]))
    time = _time_tiles(d)
    if time:
        doc.tiles(time)
    wait = waits(d)
    if wait and {"hearing", "thinking", "voicing"} <= wait.keys():
        doc.text(
            f"Each reply began {wait['total']:.1f}s after you stopped: {wait['hearing']:.1f}s "
            f"hearing you, {wait['thinking']:.1f}s thinking, {wait['voicing']:.1f}s voicing.",
            21,
            color=picture.MUTED,
            after=10,
        )


def _fixes(doc: layout.Doc, fixes: list[dict]) -> None:
    if not fixes:
        return
    doc.heading("Say it better")
    for fix in fixes:
        doc.room(150)  # an item stays on one page
        doc.text(f"You said: {fix.get('said', '')}", 24, color=picture.MUTED, after=2)
        doc.text(f"Try: {fix.get('better', '')}", 27, bold=True, after=2)
        doc.text(fix.get("why", ""), 22, color=picture.MUTED, after=18)


def _phrases(doc: layout.Doc, phrases: list[dict]) -> None:
    if not phrases:
        return
    doc.heading("Phrases for your conversations")
    for p in phrases:
        doc.room(150)
        doc.text(f"{p.get('phrase', '')} — {p.get('meaning', '')}", 26, bold=True, after=2)
        if p.get("instead_of"):
            doc.text(f"instead of “{p['instead_of']}”", 22, color=picture.MUTED, after=2)
        if p.get("example"):
            doc.text(f"“{p['example']}”", 24, color=picture.ACCENT, after=18)


def _lists(doc: layout.Doc, s: dict) -> None:
    """What to say instead of um, and what to practise tomorrow."""
    if s.get("instead_of_um"):
        doc.heading("Instead of “um”, try")
        for phrase in s["instead_of_um"]:
            doc.bullet(phrase)
    if s.get("practice"):
        doc.heading("For tomorrow")
        for n, task in enumerate(s["practice"], 1):
            doc.bullet(task, marker=f"{n}.")
