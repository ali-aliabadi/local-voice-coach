"""Modes are self-registering. Drop a .py file in this folder and it appears in the app.

A mode module declares these:

    HELP      str   one line, shown on the mode picker
    ENDPOINT  str   "fast" for conversation (latency matters)
                    "deep" for analysis (quality matters, latency does not)
    PARTNER   str   optional: who the user is talking to, as the pages name them.
                    "interviewer" when left out.
    UNLOCK    int   optional: sessions done before it opens; 1 when left out. A first
                    session sees only the UNLOCK 0 mode; after one, all are shown.
    INTERVIEW bool  optional: it is a job interview. The mode picker asks for a resume
                    when there is none, and the interviewer's verdict is written after.
                    Build the prompt with profile.system_prompt(..., interview=True) -
                    the default - and it reads the resume and the job posting.
    async def run(endpoint, io)
                    endpoint bundles .client, .model and .extra for your ENDPOINT.
                    io is the browser, for one session:
                      await io.answer()            hear, score and save one answer
                      await io.reply(endpoint, m)  speak the model's reply as it streams
                      await io.speak(text)         say a fixed line, no model
                      await io.send(**event)       anything else the page should show:
                        type="scene", text=...     the situation, shown at the top
                        type="limit", seconds=N    a countdown on the next answer
                        type="card", title=..., rows=[[label, value], ...], text=...
                      io.save_turn(role, text)     keep something written in the history
                      io.prior_turns()             what was said before a refresh
                    Loop forever - SessionClosed is raised through you and caught at the
                    edge when the user stops. Never catch it.

That is the whole contract. No registry to update, no branch in main.py to extend.
A conversation is one call to `converse` in _converse.py: copy talk.py, change the
prompt, and you have a new mode. Files starting with "_" are helpers, not modes.
"""

import importlib
import pkgutil
from types import ModuleType


def discover() -> dict[str, ModuleType]:
    """Import every mode module in this package, keyed by filename."""
    return {
        info.name: importlib.import_module(f"{__name__}.{info.name}")
        for info in pkgutil.iter_modules(__path__)
        if not info.name.startswith("_")
    }


def unlock(module: ModuleType) -> int:
    return getattr(module, "UNLOCK", 1)


def state(module: ModuleType, done: int) -> str:
    """ "open", "locked" (shown, not yet usable) or "hidden", after `done` sessions."""
    if done >= unlock(module):
        return "open"
    return "locked" if done else "hidden"
