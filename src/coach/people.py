"""Who uses this server, and how they prove it: passkeys, never passwords.

A server only this machine can reach has one person, the owner, and nobody signs in.
Name a host in ALLOWED_HOSTS - the VPS's Tailscale name, a domain - and every page asks
for a passkey first.

What is stored: each passkey's public key and signature counter (the private key never
leaves the phone, so a copy of this database signs nobody in), and sign-ins and invite
links as SHA-256 hashes of random tokens, for the same reason. Nobody signs themselves
up: an admin adds a person, which makes a one-time link, and the passkey is made on
whichever device opens it. The same link, made again, adds another device.
"""

import hashlib
import os
import secrets
import sqlite3
import time
from typing import NamedTuple

from . import store, vault

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE,
    relay    TEXT,                    -- their Relay recipient: links and reports go there
    admin    INTEGER NOT NULL DEFAULT 0,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS passkeys (
    id         TEXT PRIMARY KEY,      -- the credential id, base64url
    person_id  INTEGER NOT NULL REFERENCES people(id),
    public_key BLOB NOT NULL,
    sign_count INTEGER NOT NULL,
    added_at   TEXT NOT NULL,
    used_at    TEXT
);
CREATE TABLE IF NOT EXISTS logins (   -- one row per signed-in browser
    token_hash TEXT PRIMARY KEY,
    person_id  INTEGER NOT NULL REFERENCES people(id),
    expires    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS invites (  -- one-time links that make a passkey
    token_hash TEXT PRIMARY KEY,
    person_id  INTEGER NOT NULL REFERENCES people(id),
    expires    REAL NOT NULL
);
"""

LOGIN_DAYS = 30  # a phone stays signed in this long since its last passkey
INVITE_HOURS = 48  # someone new may not open it today
DEVICE_MINUTES = 15  # another device of your own: you are holding both
LOCAL = ("127.0.0.1", "localhost", "::1", "[::1]")

_ready: sqlite3.Connection | None = None


class Person(NamedTuple):
    id: int
    name: str
    relay: str | None
    admin: bool


def _db() -> sqlite3.Connection:
    """The store's connection, with these tables in it: a new database each test."""
    global _ready  # noqa: PLW0603 - which connection already has the tables
    connection = store.db()
    if connection is not _ready:
        connection.executescript(SCHEMA)
        _ready = connection
    return connection


def hosts() -> list[str]:
    """The names beyond localhost this server answers to (guard.py reads the same)."""
    return [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]


def required() -> bool:
    """Sign-in is required once anything but this machine can reach the server."""
    return bool(hosts())


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _person(row: sqlite3.Row | None) -> Person | None:
    return Person(row["id"], row["name"], row["relay"], bool(row["admin"])) if row else None


def get(person_id: int) -> Person | None:
    return _person(_db().execute("SELECT * FROM people WHERE id = ?", (person_id,)).fetchone())


def everyone() -> list[dict]:
    rows = _db().execute(
        "SELECT p.*, (SELECT COUNT(*) FROM passkeys k WHERE k.person_id = p.id) AS passkeys,"
        " (SELECT MAX(used_at) FROM passkeys k WHERE k.person_id = p.id) AS last_seen"
        " FROM people p ORDER BY p.id"
    )
    return [dict(r) | {"admin": bool(r["admin"])} for r in rows]


def add(name: str, relay_user: str | None = None, admin: bool = False) -> Person:
    name = " ".join(name.split())[:60]
    if not name:
        raise ValueError("A name is needed.")
    try:
        cur = _db().execute(
            "INSERT INTO people (name, relay, admin, added_at) VALUES (?, ?, ?, ?)",
            (name, (relay_user or "").strip() or None, int(admin), _now()),
        )
    except sqlite3.IntegrityError:
        raise ValueError(f"{name} is already here.") from None
    _db().commit()
    return Person(int(cur.lastrowid or 0), name, relay_user or None, admin)


def owner() -> Person:
    """The first admin: whoever runs the server. Made on first use, named after
    RELAY_USER so their reports keep going where they went before accounts."""
    query = "SELECT * FROM people WHERE admin = 1 ORDER BY id LIMIT 1"
    found = _person(_db().execute(query).fetchone())
    named = vault.value("RELAY_USER")  # not relay.recipient(): that is whoever acts
    if found is None:
        return add(named or "me", named or None, admin=True)
    if named and not found.relay:  # RELAY_USER set after the first start: take it up now
        name = named if found.name == "me" else found.name
        _db().execute("UPDATE people SET name = ?, relay = ? WHERE id = ?", (name, named, found.id))
        _db().commit()
        return found._replace(name=name, relay=named)
    return found


def set_relay(person_id: int, name: str) -> None:
    """Where their links and reports go; blank for nowhere."""
    _db().execute("UPDATE people SET relay = ? WHERE id = ?", (name.strip() or None, person_id))
    _db().commit()


def revoke(person_id: int) -> None:
    """Every passkey, sign-in and link of theirs. Their practice history is kept."""
    for table in ("passkeys", "logins", "invites"):
        _db().execute(f"DELETE FROM {table} WHERE person_id = ?", (person_id,))
    _db().commit()


# ---- invite links ----


def invite(person_id: int, minutes: float) -> str:
    """A one-time token for a link that makes a passkey for this person."""
    token = secrets.token_urlsafe(32)
    _db().execute(
        "INSERT INTO invites (token_hash, person_id, expires) VALUES (?, ?, ?)",
        (_hash(token), person_id, time.time() + minutes * 60),
    )
    _db().commit()
    return token


def invited(token: str) -> Person | None:
    """Who a link is for, while it is unused and in date. Does not use it up."""
    row = (
        _db()
        .execute(
            "SELECT p.* FROM invites i JOIN people p ON p.id = i.person_id"
            " WHERE i.token_hash = ? AND i.expires > ?",
            (_hash(token or ""), time.time()),
        )
        .fetchone()
    )
    return _person(row)


def use_invite(token: str) -> Person | None:
    person = invited(token)
    _db().execute(
        "DELETE FROM invites WHERE token_hash = ? OR expires <= ?",
        (_hash(token or ""), time.time()),
    )
    _db().commit()
    return person


def pending(person_id: int) -> bool:
    return bool(
        _db()
        .execute(
            "SELECT 1 FROM invites WHERE person_id = ? AND expires > ?", (person_id, time.time())
        )
        .fetchone()
    )


# ---- passkeys ----


def keep_passkey(person_id: int, credential_id: str, public_key: bytes, sign_count: int) -> None:
    _db().execute(
        "INSERT OR REPLACE INTO passkeys (id, person_id, public_key, sign_count, added_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (credential_id, person_id, public_key, sign_count, _now()),
    )
    _db().commit()


def passkey(credential_id: str) -> sqlite3.Row | None:
    return _db().execute("SELECT * FROM passkeys WHERE id = ?", (credential_id,)).fetchone()


def passkey_ids(person_id: int) -> list[str]:
    rows = _db().execute("SELECT id FROM passkeys WHERE person_id = ?", (person_id,))
    return [r["id"] for r in rows]


def passkey_used(credential_id: str, sign_count: int) -> None:
    _db().execute(
        "UPDATE passkeys SET sign_count = ?, used_at = ? WHERE id = ?",
        (sign_count, _now(), credential_id),
    )
    _db().commit()


# ---- sign-ins ----


def sign_in(person_id: int) -> str:
    token = secrets.token_urlsafe(32)
    _db().execute(
        "INSERT INTO logins (token_hash, person_id, expires) VALUES (?, ?, ?)",
        (_hash(token), person_id, time.time() + LOGIN_DAYS * 86400),
    )
    _db().commit()
    return token


def signed_in(token: str) -> Person | None:
    if not token:
        return None
    row = (
        _db()
        .execute(
            "SELECT p.* FROM logins l JOIN people p ON p.id = l.person_id"
            " WHERE l.token_hash = ? AND l.expires > ?",
            (_hash(token), time.time()),
        )
        .fetchone()
    )
    return _person(row)


def sign_out(token: str) -> None:
    _db().execute(
        "DELETE FROM logins WHERE token_hash = ? OR expires <= ?", (_hash(token), time.time())
    )
    _db().commit()
