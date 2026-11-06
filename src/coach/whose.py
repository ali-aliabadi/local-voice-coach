"""Whose rows these are: the person a request, socket or background task acts for.

Everything that reads or writes sessions and personal settings goes through here, so
one person never sees another's history. The owner's rows carry no person at all - the
rows from before there were accounts, and the only ones on a server nobody else reaches.
"""

from contextvars import ContextVar

# None is the owner. login.Gate sets it; asyncio tasks copy it, so the coach's work
# after a session is filed under the person who practised.
acting: ContextVar[int | None] = ContextVar("acting", default=None)


def mine(alias: str = "s") -> str:
    """SQL: the session row `alias` belongs to whoever is acting."""
    who = acting.get()
    return f"{alias}.person_id IS NULL" if who is None else f"{alias}.person_id = {int(who)}"


def own(key: str) -> str:
    """A settings-table key, for whoever is acting: the owner's keep their old names."""
    who = acting.get()
    return key if who is None else f"{key}@{int(who)}"
