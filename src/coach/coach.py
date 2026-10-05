"""The coach: a second agent that reads each answer after you give it and writes notes.

It never speaks and never interrupts. The conversation partner is told never to correct
you, because being corrected mid-answer is what makes people freeze; correction lives
here instead - written, in the background, and read once the session is over.

Notes are kind and few. A native listener lets most slips pass, so only what they would
notice, or what changes the meaning, is worth your attention.
"""

import asyncio
import json
import re

from . import backends, history, llm, profile, settings, store

# What a fix is about, so the ones you repeat can be counted across sessions.
KINDS = (
    "articles", "tense", "prepositions", "agreement", "word order", "word choice",
    "phrasing", "other",
)  # fmt: skip

NOTES_PROMPT = (
    "You are a kind, experienced English coach. A learner is practising spoken English "
    "out loud. You get one thing they said, transcribed by speech recognition, and what they "
    "were replying to. Write brief notes that help them sound more natural.\n\n"
    "Rules:\n"
    "- Be warm and specific. At most 3 fixes, most useful first. Only point out what a "
    "native listener would notice, or what changes the meaning. Let small slips go.\n"
    "- Never mention 'um', 'uh', pauses or hesitation: those are measured elsewhere.\n"
    "- Speech recognition mishears. A strange word that sounds like a likely one, or a "
    "mangled name or foreign word, was probably misheard: ignore it, never blame the speaker.\n"
    "- Spelling, capitals, digits and punctuation were written by the transcriber, not said "
    "by the speaker: never correct them.\n"
    "- A fix must keep what they meant. If you cannot tell what they meant, leave it out.\n"
    "- Nothing worth fixing is a good result: return no fixes.\n"
    "- Suggest 1-3 natural phrases, idioms or short sayings for this moment. Where one could "
    "replace something they actually said, quote their words in instead_of and rewrite "
    "their sentence with the phrase in example, so they see exactly where it fits.\n\n"
    "Reply with JSON only:\n"
    '{"fixes": [{"said": "their words", "better": "the natural version", '
    f'"why": "a few words", "kind": one of {list(KINDS)}}}], '
    '"natural": "how a native speaker might say the whole thing, 1-3 sentences", '
    '"phrases": [{"phrase": "...", "meaning": "...", "instead_of": "their words, or empty", '
    '"example": "their sentence, said with the phrase"}], '
    '"praise": "one specific thing they did well"}'
)

SUMMARY_PROMPT = (
    "You are a kind, experienced English coach. Below is a whole spoken practice "
    "conversation, with the notes already written on each of the learner's answers. Write "
    "the session summary: short, warm and practical, speaking to the learner as 'you'. "
    "Prefer patterns that repeat across answers over one-off slips. The transcript comes "
    "from speech recognition: never turn a likely mishearing into advice, and never advise "
    "on similar-sounding words or pronunciation from the text alone.\n\n"
    "Reply with JSON only:\n"
    '{"recap": "1-2 sentences on what was talked about, in the third person, so the next '
    'conversation can remember it", '
    '"work_on": ["the 3 most useful things to practise, one short sentence each"], '
    '"phrases": [{"phrase": "...", "meaning": "...", "instead_of": "their words, or empty", '
    '"example": "their sentence, said with it"}] (up to 5 worth learning), '
    '"instead_of_um": ["2-3 short phrases to buy thinking time instead of um, suited to '
    'how they talk"], '
    '"went_well": "1-2 sentences on what went well"}'
)

# In the order they were queued: notes, then the summary, then the study sheet.
_pending: dict[int, list[asyncio.Task]] = {}
failed: dict[int, str] = {}  # the last thing that went wrong per session, for the page to say


def endpoint():
    """The coach's model, or None when the coach is switched off."""
    backend = backends.BY_KEY.get(settings.get("coach_backend"))
    return llm.endpoint_for(backend) if backend else None


def parse(text: str) -> dict | None:
    """Models wrap JSON in code fences or chatter; take the outermost object."""
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        return None


def pending(session_id: int) -> bool:
    return bool(_pending.get(session_id))


def queued() -> list[asyncio.Task]:
    """Everything still being written, for every session."""
    return [task for tasks in _pending.values() for task in tasks]


async def settled(session_id: int) -> None:
    """Wait for the coach's work on a session. A task that is itself part of that work
    waits only for what was queued before it - the summary for the notes, the sheet for
    the summary - or two of them would each wait for the other forever."""
    tasks = list(_pending.get(session_id, ()))
    me = asyncio.current_task()
    earlier = tasks[: tasks.index(me)] if me in tasks else tasks
    await asyncio.gather(*earlier, return_exceptions=True)


def later(session_id: int, work) -> None:
    """Run `work` in the background. The conversation never waits for the coach."""

    async def safely():
        try:
            await work
        except Exception as exc:  # a failed note must never reach the session
            failed[session_id] = llm._said(exc)[:300]
            print(f"  coach: {failed[session_id][:160]}")

    failed.pop(session_id, None)  # a new attempt clears the last failure
    task = asyncio.create_task(safely())
    _pending.setdefault(session_id, []).append(task)
    task.add_done_callback(lambda t: _pending[session_id].remove(t))


def _system(prompt: str) -> str:
    first = profile.get("native_language").strip()
    return prompt + (f"\n\nThe learner's first language is {first}." if first else "")


async def _note(ep, turn_id: int, asked: str, said: str) -> None:
    reply = await llm.patiently(
        ep,
        [
            {"role": "system", "content": _system(NOTES_PROMPT)},
            {"role": "user", "content": f"They were replying to: {asked}\n\nThey said: {said}"},
        ],
    )
    notes = parse(reply.text) or ({"text": reply.text} if reply.text else None)
    if notes:
        store.db().execute("UPDATE turns SET notes = ? WHERE id = ?", (json.dumps(notes), turn_id))
        store.db().commit()


def note(session_id: int, turn_id: int, asked: str, said: str) -> None:
    """Write notes on one answer, in the background."""
    ep = endpoint()
    if ep:
        later(session_id, _note(ep, turn_id, asked, said))


async def _summarise(ep, session_id: int) -> None:
    await settled(session_id)  # the notes go into the summary
    rows = (
        store.db()
        .execute(
            "SELECT role, text, notes FROM turns WHERE session_id = ? AND role != 'review'"
            " ORDER BY id",
            (session_id,),
        )
        .fetchall()
    )
    answers = sum(r["role"] == "you" for r in rows)
    lines = []
    for r in rows:
        lines.append(f"{'LEARNER' if r['role'] == 'you' else 'PARTNER'}: {r['text']}")
        if r["notes"]:
            lines.append(f"  notes: {r['notes']}")
    reply = await llm.patiently(
        ep,
        [
            {"role": "system", "content": _system(SUMMARY_PROMPT)},
            {"role": "user", "content": "\n".join(lines)},
        ],
    )
    summary = parse(reply.text)
    if summary:
        summary["answers"] = answers  # what it covers, so a resumed session is redone
        store.db().execute(
            "UPDATE sessions SET summary = ? WHERE id = ?", (json.dumps(summary), session_id)
        )
        store.db().commit()


def summarise(session_id: int) -> None:
    """Summarise the session once its notes are in, unless the summary is already current."""
    ep = endpoint()
    row = (
        store.db()
        .execute(
            "SELECT s.summary, (SELECT COUNT(*) FROM turns t WHERE t.session_id = s.id"
            "  AND t.role = 'you') AS answers FROM sessions s WHERE s.id = ?",
            (session_id,),
        )
        .fetchone()
    )
    if not ep or not row or not history.is_counted(session_id):
        return
    if (parse(row["summary"]) or {}).get("answers") == row["answers"]:
        return
    later(session_id, _summarise(ep, session_id))


def catch_up(session_id: int) -> None:
    """Notes for every answer that has none, then the summary. For older sessions, or
    notes lost to a restart."""
    rows = (
        store.db()
        .execute(
            "SELECT id, role, text, notes FROM turns WHERE session_id = ? AND role != 'review'"
            " ORDER BY id",
            (session_id,),
        )
        .fetchall()
    )
    asked = ""
    for r in rows:
        if r["role"] != "you":
            asked = r["text"]
        elif not r["notes"]:
            note(session_id, r["id"], asked, r["text"])
    summarise(session_id)
