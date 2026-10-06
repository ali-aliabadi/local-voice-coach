"""The interviewer's verdict: after an interview, the feedback a real one would submit.

A rating out of 10, a decision on a five-step hiring scale, a score for each area, and
the evidence for each. A model writes it after the session, in the coach's queue; the
session page shows all of it, and Telegram only its headline, inside the session's report
- one more message per session would be spam.

It never judges the English. The transcript comes from speech recognition, and the
English is the coach's job: communication here means a clear, structured answer.
"""

import json

from . import backends, coach, config, history, llm, profile, settings, sheet, store
from .modes import discover

DECISIONS = ("No", "Not sure", "Yes", "Definitely hire", "They could have my job")
AREAS = (
    "technical depth", "problem solving", "communication", "ownership and impact",
    "resume holds up",
)  # fmt: skip

VERDICT_PROMPT = (
    "You just interviewed a candidate for a software engineering role. Below are their "
    "resume and the job posting, when there were any, then the transcript of the interview. "
    "Write the feedback you would submit to the hiring committee.\n\n"
    "Be honest and calibrated the way real interviewers are: most candidates are not a 9, "
    "and 'Yes' means you would hire them at the level they are aiming for. 'They could have "
    "my job' is only for someone so strong your own seat feels at risk. Judge what they "
    "said: depth, specifics, ownership, reasoning, and whether their answers backed up what "
    "the resume claims. The transcript comes from speech recognition: ignore words that look "
    "misheard, and never judge grammar, accent, vocabulary or spelling. Communication means "
    "clear, structured, concise answers.\n\n"
    "Reply with JSON only:\n"
    '{"rating": a whole number from 1 to 10, '
    f'"decision": one of {json.dumps(DECISIONS)}, '
    f'"level": the level they came across at, one of {json.dumps(profile.SENIORITY[1:])}, '
    '"scores": {' + ", ".join(f'"{area}": 1-10' for area in AREAS) + "}, "
    '"summary": "2-3 sentences, as written to the committee", '
    '"strengths": [up to 3, quoting what they said], '
    '"concerns": [up to 3, quoting what they said], '
    '"would_change": "what would have moved the decision up", '
    '"votes": [only if more than one interviewer spoke, one each: '
    '{"name": "...", "decision": "...", "why": "one line"}]}'
)


def endpoint() -> llm.Endpoint | None:
    """The verdict's model, or None when it is switched off."""
    backend = backends.BY_KEY.get(settings.get("verdict_backend"))
    return llm.endpoint_for(backend) if backend else None


def is_interview(session_id: int) -> bool:
    row = store.db().execute("SELECT mode FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return bool(row) and getattr(discover().get(row["mode"]), "INTERVIEW", False)


def _score(value: object) -> int | None:
    """A whole number from 1 to 10, or None: models send "7", 7.0, or prose."""
    try:
        score = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
    return score if 1 <= score <= 10 else None


def valid(found: dict | None) -> dict | None:
    """The verdict, if it says what a verdict has to: a rating out of 10 and a decision."""
    if not found or found.get("decision") not in DECISIONS:
        return None
    rating = _score(found.get("rating"))
    if rating is None:
        return None
    scores = found.get("scores")
    marked = {str(k): _score(v) for k, v in scores.items()} if isinstance(scores, dict) else {}
    return {
        **found,
        "rating": rating,
        "scores": {area: score for area, score in marked.items() if score is not None},
    }


def headline(verdict: dict) -> str:
    return f"{verdict['rating']}/10 · {verdict['decision']}"


def _transcript(session_id: int) -> tuple[str, int]:
    """The interview as the committee would read it, and how many answers it holds. The
    review mode's written critiques are left out: they are not the interview."""
    rows = store.db().execute(
        "SELECT role, text FROM turns WHERE session_id = ? AND role != 'review' ORDER BY id",
        (session_id,),
    )
    lines, answers = [], 0
    for r in rows:
        answers += r["role"] == "you"
        who = "CANDIDATE" if r["role"] == "you" else r["role"].split(":")[0].upper()
        lines.append(f"{who}: {r['text']}")
    return "\n".join(lines), answers


async def write(session_id: int) -> None:
    """Write the verdict, after whatever the coach queued before it."""
    await coach.settled(session_id)
    ep = endpoint()
    transcript, answers = _transcript(session_id)
    if not ep or not answers:
        return
    papers = [
        f"<{key}>\n{profile.get(key).strip()[: config.DOCUMENT_CHARS]}\n</{key}>"
        for key in ("resume", "job")
        if profile.get(key).strip()
    ]
    reply = await llm.patiently(
        ep,
        [
            {"role": "system", "content": VERDICT_PROMPT},
            {"role": "user", "content": "\n\n".join([*papers, transcript])},
        ],
        max_tokens=sheet.SHEET_TOKENS,
    )
    found = valid(coach.parse(reply.text))
    if found is None:
        raise RuntimeError("The interviewer's verdict came back malformed. Ask for it again.")
    found["answers"] = answers  # what it covers, so a resumed interview is judged again
    store.db().execute(
        "UPDATE sessions SET verdict = ? WHERE id = ?", (json.dumps(found), session_id)
    )
    store.db().commit()


def later(session_id: int) -> None:
    """Write it in the background, for an interview that counts, unless it is current."""
    if not endpoint() or not history.is_counted(session_id) or not is_interview(session_id):
        return
    row = (
        store.db()
        .execute(
            "SELECT s.verdict, (SELECT COUNT(*) FROM turns t WHERE t.session_id = s.id"
            "  AND t.role = 'you') AS answers FROM sessions s WHERE s.id = ?",
            (session_id,),
        )
        .fetchone()
    )
    if (coach.parse(row["verdict"]) or {}).get("answers") == row["answers"]:
        return
    coach.later(session_id, write(session_id))
