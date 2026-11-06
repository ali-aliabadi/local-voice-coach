"""The server's keys and Telegram connection: set by an admin in the app, or in .env.

Anything set in the environment wins and cannot be changed from the app, so a server
configured by hand behaves as it always did. What the app stores sits in the settings
table under "vault:" keys, in plain text: a copy of the database is a copy of these keys,
the trade made so that setting up needs no shell. Secrets go one way. The browser is told
that a key is set and its last four characters, never the key.

Gemini keys are a pool, not a choice: the app's list, then GEMINI_API_KEY and
GEMINI_API_KEYS. The old single "gemini_api_key" setting is read as part of the list and
folded into it the first time the list changes.
"""

import hashlib
import os
import re

from . import store

RELAY = ("RELAY_URL", "RELAY_APP", "RELAY_USER", "RELAY_API_KEY")
SECRET = {"RELAY_API_KEY"}
_KEYS = "vault:GEMINI_API_KEYS"
_LEGACY = "gemini_api_key"  # the Settings field before this list


def _stored(key: str) -> str:
    row = store.db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return (row["value"] or "") if row else ""


def _keep(key: str, value: str) -> None:
    if value:
        store.db().execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    else:
        store.db().execute("DELETE FROM settings WHERE key = ?", (key,))
    store.db().commit()


def value(name: str) -> str:
    """The environment's, else the app's, else ""."""
    return os.environ.get(name, "").strip() or _stored(f"vault:{name}").strip()


def source(name: str) -> str:
    """ "env", "app" or "" - where `value(name)` comes from."""
    if os.environ.get(name, "").strip():
        return "env"
    return "app" if _stored(f"vault:{name}").strip() else ""


def put(name: str, text: str) -> None:
    """Store one of RELAY; blank removes it. The environment's own value is left to win."""
    if name not in RELAY:
        raise KeyError(name)
    _keep(f"vault:{name}", " ".join(text.split()))


def _split(raw: str) -> list[str]:
    return [k for k in re.split(r"[\s,]+", raw) if k]


def _app_keys() -> list[str]:
    return list(dict.fromkeys(_split(_stored(_KEYS)) + _split(_stored(_LEGACY))))


def _env_keys() -> list[str]:
    return _split(f"{os.environ.get('GEMINI_API_KEY', '')},{os.environ.get('GEMINI_API_KEYS', '')}")


def gemini_keys() -> list[str]:
    """Every key, in order, once: the app's first, then the environment's."""
    return list(dict.fromkeys(_app_keys() + _env_keys()))


def key_id(key: str) -> str:
    """How the browser names a key to remove it: not the key, nor enough to find it."""
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def masked(secret: str) -> str:
    return f"…{secret[-4:]}" if len(secret) > 8 else "…"  # too short to show any of it


def listed() -> list[dict]:
    """The pool as the browser sees it."""
    env = set(_env_keys())
    return [
        {"id": key_id(k), "shown": masked(k), "from": "env" if k in env else "app"}
        for k in gemini_keys()
    ]


def _save_keys(keys: list[str]) -> None:
    _keep(_KEYS, ",".join(keys))
    _keep(_LEGACY, "")


def add_key(key: str) -> None:
    key = key.strip()
    if not key or not re.fullmatch(r"[\w.-]{20,200}", key):
        raise ValueError("That does not look like a Gemini key.")
    _save_keys([*_app_keys(), key] if key not in _app_keys() else _app_keys())


def remove_key(found: str) -> bool:
    """False when no key the app holds has that id (one from .env stays where it is)."""
    keys = _app_keys()
    kept = [k for k in keys if key_id(k) != found]
    if len(kept) == len(keys):
        return False
    _save_keys(kept)
    return True
