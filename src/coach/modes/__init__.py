"""Modes are self-registering. Drop a .py file in this folder and it appears in --mode.

A mode module declares three things:

    HELP      str   one line, shown in --help
    ENDPOINT  str   "fast" for conversation (latency matters)
                    "deep" for analysis (quality matters, latency does not)
    async def run(endpoint, transcriber, io)
                    endpoint bundles .client, .model and .extra for your ENDPOINT.
                    io is the browser: await io.record(), await io.say(text, voice),
                    await io.send(**event), io.save_answer(...).
                    Loop forever - SessionClosed is raised through you and caught at the
                    edge when the user stops. Never catch it.

That is the whole contract. No registry to update, no branch in main.py to extend.
Copy talk.py, change the prompt, and you have a new mode.
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
