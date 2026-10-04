"""Modes are self-registering. Drop a .py file in this folder and it appears in the app.

A mode module declares these:

    HELP      str   one line, shown on the mode picker
    ENDPOINT  str   "fast" for conversation (latency matters)
                    "deep" for analysis (quality matters, latency does not)
    PARTNER   str   optional: who the user is talking to, as the pages name them.
                    "interviewer" when left out.
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


def discover() -> dict:
    """Import every mode module in this package, keyed by filename."""
    return {
        info.name: importlib.import_module(f"{__name__}.{info.name}")
        for info in pkgutil.iter_modules(__path__)
        if not info.name.startswith("_")
    }
