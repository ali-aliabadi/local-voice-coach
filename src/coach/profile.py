"""Who the candidate is, so the interviewer behaves like a trainer who knows them.

Stored in the settings table under `profile:` keys, the same way prompt overrides are.
`as_prompt()` renders it into every system prompt, which is the entire point: a generic
interviewer asks generic questions.
"""

import json
from dataclasses import dataclass, field

from . import history, settings, store

SENIORITY = ("", "intern", "junior", "mid-level", "senior", "staff", "principal")


@dataclass(frozen=True)
class Field:
    key: str
    label: str  # what the profile form asks
    term: str  # how it reads inside a prompt
    kind: str = "text"
    help: str = ""
    placeholder: str = ""
    choices: tuple[str, ...] = field(default_factory=tuple)


FIELDS: tuple[Field, ...] = (
    Field("name", "What should the interviewer call you?", "Name", placeholder="Ali"),
    Field("role", "Role you are interviewing for", "Target role", placeholder="Backend engineer"),
    Field("seniority", "Level you are aiming at", "Level", kind="select", choices=SENIORITY),
    Field("years", "Years of experience", "Years of experience", kind="number"),
    Field(
        "companies",
        "Companies or kind of company",
        "Targeting",
        placeholder="Series B startups, remote",
    ),
    Field(
        "stack",
        "What you actually work with",
        "Works with",
        placeholder="Python, Postgres, Kubernetes",
        help="The interviewer digs into these instead of guessing.",
    ),
    Field(
        "background",
        "A sentence or two about your experience",
        "Background",
        kind="textarea",
        help="The project you would bring up in an interview. Gives it something to pull on.",
    ),
    Field(
        "focus",
        "What you want to get better at",
        "Wants to improve",
        kind="textarea",
        placeholder="System design. I freeze when asked to estimate scale.",
        help="The trainer leans on this. Be specific about what goes wrong.",
    ),
    Field(
        "native_language",
        "Your first language",
        "First language",
        placeholder="Persian",
        help="Only so it can pitch its English at you. It will never correct your grammar.",
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
            "choices": list(f.choices),
            "value": get(f.key),
        }
        for f in FIELDS
    ]


def is_set() -> bool:
    return any(get(f.key).strip() for f in FIELDS)


# All a conversation partner needs: what to call them and how to pitch the English.
# Stack, role and focus would pull every chat back to engineering.
PERSONAL = ("name", "native_language")


def as_prompt(interview: bool = True) -> str:
    """The profile as a block to append to a system prompt. Empty if nothing is filled in.

    Only non-empty fields appear, so a half-filled profile does not feed the model a list
    of blanks to speculate about.
    """
    fields = FIELDS if interview else [BY_KEY[k] for k in PERSONAL]
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
        + "\n\nUse this to choose what to ask: pitch the difficulty at their level, dig "
        "into the stack and projects they actually named, and push on what they said they "
        "want to improve. Never read this back to them or mention that you have it."
    )


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
    of their CV. `memory` adds what earlier sessions were about.
    """
    prompt = settings.prompt(mode, default) + as_prompt(interview)
    if memory:
        prompt += recaps()
    if pacing:
        prompt += coaching_note(history.recent())
    return prompt
