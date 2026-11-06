"""User-editable settings, stored in SQLite and rendered as a form by the browser.

Adding a knob is one row in SPEC. The settings screen builds itself from this, so there
is no frontend change and no hand-written form field.

Mode prompts are not in SPEC: their defaults live in the mode files, and only overrides
are stored here. See `prompt()`.
"""

import os
from typing import Any

from . import config, store, whose
from .knobs import SHARED, SPEC, WHISPER_CHOICES, Setting

__all__ = ["SHARED", "SPEC", "WHISPER_CHOICES", "Setting"]


_ENV_FALLBACK = {
    "gemini_api_key": "GEMINI_API_KEY",
    "lm_studio_url": "LM_STUDIO_URL",
    "coach_backend": "COACH_BACKEND",
}


def _coerce(raw: str, default: Any) -> Any:
    if isinstance(default, bool):
        return raw.lower() in ("1", "true", "yes")
    if isinstance(default, int):
        return int(float(raw))
    if isinstance(default, float):
        return float(raw)
    return raw


def _stored(key: str) -> str | None:
    row = store.db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None and row["value"] != "" else None


def _key(key: str) -> str:
    """Where a knob is kept for whoever is acting: shared ones once, for everybody."""
    return key if key in SHARED else whose.own(key)


def get(key: str) -> Any:
    """Your stored value, else the owner's (where a new person starts), else the
    environment, else the declared default."""
    spec = SPEC[key]
    raw = _stored(_key(key))
    raw = raw if raw is not None else _stored(key)
    if raw is not None:
        return _coerce(raw, spec.default)
    env = os.environ.get(_ENV_FALLBACK.get(key, ""), "")
    if env:
        return _coerce(env, spec.default)
    return spec.default


def _store(key: str, value: str | None) -> None:
    """None deletes the row, so the declared default applies again."""
    if value is None:
        store.db().execute("DELETE FROM settings WHERE key = ?", (key,))
    else:
        store.db().execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    store.db().commit()


def set(key: str, value: Any) -> None:
    """Only differences from the default are stored. The form posts every field, and
    storing them all froze each default at whatever it was on the day you hit Save, so a
    better default never reached you. Raises ValueError for a value of the wrong type."""
    if key not in SPEC:
        raise KeyError(key)
    default = SPEC[key].default
    raw = str(value)
    where = _key(key)
    if where != key:  # someone else's: what they would get without a row of their own
        owners = _stored(key)
        default = _coerce(owners, default) if owners is not None else default
    _store(where, None if raw == "" or _coerce(raw, default) == default else raw)


def prompt(name: str, default: str) -> str:
    """A mode's system prompt: the user's override if there is one, else the mode's own.

    `name` is the mode ("talk"), or the mode and attribute ("review:critique_prompt") for
    a mode that has more than one. The default stays in the mode file that owns it.
    """
    found = _stored(whose.own(f"prompt:{name}")) or _stored(f"prompt:{name}") or ""
    return found if found.strip() else default


def set_prompt(name: str, value: str, default: str | None = None) -> None:
    """Blank, or identical to the mode's own prompt, means no override."""
    _store(whose.own(f"prompt:{name}"), None if not value.strip() or value == default else value)


def as_form(choices: dict[str, tuple[str, ...]] | None = None) -> list[dict]:
    """The whole settings form as data, for the browser to render. Secrets are masked.

    `choices` fills selects whose options are only known at request time: the voices
    Kokoro loaded, the models in the catalogue."""
    out = []
    for key, spec in SPEC.items():
        options = (choices or {}).get(key, spec.choices)
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
                "choices": list(options),
                "value": value,
                "isSet": bool(get(key)) if spec.secret else None,
            }
        )
    return out


def api_key() -> str:
    return get("gemini_api_key") or config.API_KEY
