"""Who the candidate is, so the interviewer behaves like a trainer who knows them.

Stored in the settings table under `profile:` keys, the same way prompt overrides are.
`as_prompt()` renders it into every system prompt, which is the entire point: a generic
interviewer asks generic questions.
"""

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


def as_prompt() -> str:
    """The profile as a block to append to a system prompt. Empty if nothing is filled in.

    Only non-empty fields appear, so a half-filled profile does not feed the model a list
    of blanks to speculate about.
    """
    lines = [f"- {f.term}: {get(f.key).strip()}" for f in FIELDS if get(f.key).strip()]
    if not lines:
        return ""
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
        f"{recent['fillers']:.1f} filler words and {recent['lead_in']:.1f}s of silence "
        "before starting, per answer. If they are hesitating a lot, ask shorter and more "
        "concrete questions. Never mention these numbers or their speech. Never correct "
        "their English."
    )


def system_prompt(mode: str, default: str, pacing: bool = True) -> str:
    """The interviewer's full instructions: the mode's prompt, the user's override if
    there is one, who they are, and how they have been speaking lately.

    Every mode builds its system message through here, which is what turns a generic
    interviewer into one that knows the candidate.

    `pacing` is off for written critique, where delivery is not being judged.
    """
    prompt = settings.prompt(mode, default) + as_prompt()
    if pacing:
        prompt += coaching_note(history.recent())
    return prompt
