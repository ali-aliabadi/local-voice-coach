"""Who the candidate is, so the interviewer behaves like a trainer who knows them.

Stored in the settings table under `profile:` keys, the same way prompt overrides are.
`as_prompt()` renders it into every system prompt, which is the entire point: a generic
interviewer asks generic questions.
"""

import json
from dataclasses import dataclass

from . import config, history, settings, store


@dataclass(frozen=True)
class Field:
    key: str
    label: str  # what the profile form asks
    term: str  # how it reads inside a prompt
    kind: str = "text"
    help: str = ""
    placeholder: str = ""


# No role, stack or years: the resume and the job posting say all that, and asking
# everyone for their tech stack made a conversation app look like an engineering one.
FIELDS: tuple[Field, ...] = (
    Field("name", "What should your partner call you?", "Name"),
    Field(
        "native_language",
        "Your first language",
        "First language",
        help="Only so it can pitch its English at you. It will never correct your grammar.",
    ),
    Field(
        "focus",
        "What you want to get better at in interviews",
        "Wants to improve",
        kind="textarea",
        placeholder="Long pauses before I answer a technical question.",
        help="The interviewer leans on this. Be specific about what goes wrong.",
    ),
    Field(
        "resume",
        "Your resume",
        "Resume",
        kind="document",
        help="Upload it or paste it. The interviewer reads exactly this text, so check what "
        "came out of the file.",
    ),
    Field(
        "job",
        "The job you are interviewing for",
        "Job posting",
        kind="document",
        help="Optional. The posting: the interviewer works there and asks against it.",
    ),
)

BY_KEY = {f.key: f for f in FIELDS}


def get(key: str) -> str:
    row = (
        store.db()
        .execute("SELECT value FROM settings WHERE key = ?", (f"profile:{key}",))
        .fetchone()
    )
    return row["value"] if row else ""


def save(values: dict) -> None:
    rows = [(f"profile:{k}", str(v)) for k, v in values.items() if k in BY_KEY]
    if not rows:
        return
    store.db().executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        rows,
    )
    store.db().commit()


def as_form() -> list[dict]:
    return [
        {
            "key": f.key,
            "label": f.label,
            "kind": f.kind,
            "help": f.help,
            "placeholder": f.placeholder,
            "value": get(f.key),
        }
        for f in FIELDS
    ]


def is_set() -> bool:
    return any(get(f.key).strip() for f in FIELDS)


# All a conversation partner needs: what to call them and how to pitch the English.
# Their interview focus would pull every chat back to interviews.
PERSONAL = ("name", "native_language")
# An interviewer's notes on them. The resume and the job posting are read differently.
NOTES = tuple(f.key for f in FIELDS if f.kind != "document")


def as_prompt(interview: bool = True) -> str:
    """The profile as a block to append to a system prompt. Empty if nothing is filled in.

    Only non-empty fields appear, so a half-filled profile does not feed the model a list
    of blanks to speculate about.
    """
    fields = [BY_KEY[k] for k in (NOTES if interview else PERSONAL)]
    lines = [f"- {f.term}: {get(f.key).strip()}" for f in fields if get(f.key).strip()]
    if not lines:
        return ""
    if not interview:
        return (
            "\n\nYou are talking with:\n"
            + "\n".join(lines)
            + "\n\nNever read this back to them or mention that you have it."
        )
    return (
        "\n\nYou are interviewing this specific person:\n"
        + "\n".join(lines)
        + "\n\nUse this to choose what to ask, and push on what they said they want to "
        "improve. Never read this back to them or mention that you have it."
    )


def reading() -> str:
    """The resume and the job posting, for an interviewer. Unlike the rest of the profile,
    meant to be referred to: every real interviewer has read your resume before you walk in."""
    resume, job = (get(key).strip()[: config.DOCUMENT_CHARS] for key in ("resume", "job"))
    text = ""
    if resume:
        text += (
            "\n\nTheir resume, which you read before the interview, as every interviewer "
            f"does:\n<resume>\n{resume}\n</resume>\nRefer to it the way a real interviewer "
            "does: name the company or project you are asking about, ask them to walk you "
            "through it, and probe the claims - what they personally did, why they chose what "
            "they chose, how they knew it worked. Never recite it back to them."
        )
    if job:
        text += (
            "\n\nThe job they are interviewing for. You work at this company and are hiring "
            f"for this role:\n<job>\n{job}\n</job>\nAsk against what the role requires, and "
            "answer their questions about the role and the team from this posting."
        )
    return text


def coaching_note(recent: dict | None) -> str:
    """Recent delivery stats, for pacing only.

    Kept separate from `as_prompt` and worded defensively: the interviewer must never
    comment on the candidate's speech, because being told you say "um" mid-answer is
    exactly what makes people freeze.
    """
    if not recent or not recent.get("answers"):
        return ""
    return (
        f"\n\nFor pacing only, their recent delivery: {recent['wpm']:.0f} words per minute, "
        f"{recent['fillers']:.1f} filler words per 100 words, and {recent['lead_in']:.1f}s "
        "of silence before starting each answer. If they are hesitating a lot, ask shorter "
        "and more concrete questions. Never mention these numbers or their speech. Never "
        "correct their English."
    )


def recaps(limit: int = 3) -> str:
    """What earlier conversations were about, from the coach's recaps. Without it every
    session starts from nothing, and "do you remember?" gets a bluff."""
    rows = store.db().execute(
        "SELECT started_at, summary FROM sessions WHERE summary IS NOT NULL"
        " ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    recaps = [(r["started_at"][:10], json.loads(r["summary"]).get("recap")) for r in rows]
    lines = [f"- {day}: {recap}" for day, recap in recaps if recap]
    if not lines:
        return ""
    return (
        "\n\nEarlier conversations with them, most recent first. Bring one up only when it "
        "fits naturally, the way a friend would:\n" + "\n".join(lines)
    )


def system_prompt(
    mode: str, default: str, pacing: bool = True, interview: bool = True, memory: bool = False
) -> str:
    """The interviewer's full instructions: the mode's prompt, the user's override if
    there is one, who they are, and how they have been speaking lately.

    Every mode builds its system message through here, which is what turns a generic
    interviewer into one that knows the candidate.

    `pacing` is off for written critique, where delivery is not being judged.
    `interview` is off for plain conversation, which gets their name and language instead
    of their CV. `memory` adds what earlier sessions were about. An interview also gets
    the resume and the job posting.
    """
    prompt = settings.prompt(mode, default) + as_prompt(interview)
    if interview:
        prompt += reading()
    if memory:
        prompt += recaps()
    if pacing:
        prompt += coaching_note(history.recent())
    return prompt
