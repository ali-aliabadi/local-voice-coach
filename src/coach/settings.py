"""User-editable settings, stored in SQLite and rendered as a form by the browser.

Adding a knob is one row in SPEC. The settings screen builds itself from this, so there
is no frontend change and no hand-written form field.

Mode prompts are not in SPEC: their defaults live in the mode files, and only overrides
are stored here. See `prompt()`.
"""

import os
from dataclasses import dataclass, field
from typing import Any

from . import config, store

WHISPER_CHOICES = ("tiny.en", "base.en", "small.en", "medium.en", "distil-small.en")


@dataclass(frozen=True)
class Setting:
    default: Any
    label: str
    group: str
    kind: str = "text"  # text | number | password | select | textarea
    help: str = ""
    secret: bool = False  # never sent back to the browser
    restart: bool = False  # takes effect on the next server start
    step: float | None = None
    choices: tuple[str, ...] = field(default_factory=tuple)


SPEC: dict[str, Setting] = {
    # ---- Backends ----
    "gemini_api_key": Setting(
        "",
        "Gemini API key",
        "Backends",
        kind="password",
        secret=True,
        help="Free key at aistudio.google.com/apikey. Stored locally, never displayed again.",
    ),
    "lm_studio_url": Setting(
        "http://localhost:1234/v1",
        "LM Studio URL",
        "Backends",
        help="Where to reach local models. Leave as-is unless you changed the port.",
    ),
    # ---- Scoring ----
    "pause_seconds": Setting(
        0.6,
        "Pause threshold",
        "Scoring",
        kind="number",
        step=0.1,
        help="A silence longer than this counts as a hesitation. Lower it to be harder on yourself.",
    ),
    "filler_words": Setting(
        "um uh er ah hmm mm",
        "Filler words",
        "Scoring",
        help="Space separated. Repeated letters are matched too, so 'mm' also catches 'mmmm'.",
    ),
    "audio_retention_days": Setting(
        7,
        "Keep recordings for (days)",
        "Scoring",
        kind="number",
        help="Recordings are deleted after this many days. 0 keeps them forever.",
    ),
    # ---- Model ----
    "temperature": Setting(0.7, "Temperature", "Model", kind="number", step=0.1),
    "history_turns": Setting(
        8,
        "History turns",
        "Model",
        kind="number",
        help="Question/answer pairs kept in context. Higher costs more per turn.",
    ),
    "reply_max_tokens": Setting(200, "Reply max tokens", "Model", kind="number"),
    "review_max_tokens": Setting(
        2500,
        "Review max tokens",
        "Model",
        kind="number",
        help="Thinking models spend this budget reasoning before they write. Keep it generous.",
    ),
    "tts_voice": Setting("am_puck", "Interviewer voice", "Model", kind="select"),
    "tts_speed": Setting(1.0, "Speech speed", "Model", kind="number", step=0.1),
    "whisper_model": Setting(
        "small.en",
        "Whisper model",
        "Model",
        kind="select",
        restart=True,
        choices=WHISPER_CHOICES,
        help="Smaller is faster and less accurate. Takes effect after a restart.",
    ),
}

_ENV_FALLBACK = {"gemini_api_key": "GEMINI_API_KEY", "lm_studio_url": "LM_STUDIO_URL"}


def _coerce(raw: str, default: Any) -> Any:
    if isinstance(default, bool):
        return raw.lower() in ("1", "true", "yes")
    if isinstance(default, int):
        return int(float(raw))
    if isinstance(default, float):
        return float(raw)
    return raw


def get(key: str) -> Any:
    """Stored value, else the environment, else the declared default."""
    spec = SPEC[key]
    row = store.db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is not None and row["value"] != "":
        return _coerce(row["value"], spec.default)
    env = os.environ.get(_ENV_FALLBACK.get(key, ""), "")
    if env:
        return _coerce(env, spec.default)
    return spec.default


def set(key: str, value: Any) -> None:  # noqa: A001 - reads better than set_value here
    if key not in SPEC:
        raise KeyError(key)
    store.db().execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    store.db().commit()


def prompt(name: str, default: str) -> str:
    """A mode's system prompt: the user's override if there is one, else the mode's own.

    `name` is the mode ("talk"), or the mode and attribute ("review:critique_prompt") for
    a mode that has more than one. The default stays in the mode file that owns it.
    """
    row = (
        store.db()
        .execute("SELECT value FROM settings WHERE key = ?", (f"prompt:{name}",))
        .fetchone()
    )
    return row["value"] if row and row["value"].strip() else default


def set_prompt(name: str, value: str) -> None:
    store.db().execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (f"prompt:{name}", value),
    )
    store.db().commit()


def as_form(voices: tuple[str, ...] = ()) -> list[dict]:
    """The whole settings form as data, for the browser to render. Secrets are masked."""
    out = []
    for key, spec in SPEC.items():
        choices = voices if key == "tts_voice" else spec.choices
        value = "" if spec.secret else get(key)
        out.append(
            {
                "key": key,
                "label": spec.label,
                "group": spec.group,
                "kind": spec.kind,
                "help": spec.help,
                "restart": spec.restart,
                "step": spec.step,
                "choices": list(choices),
                "value": value,
                "isSet": bool(get(key)) if spec.secret else None,
            }
        )
    return out


def api_key() -> str:
    return get("gemini_api_key") or config.API_KEY
