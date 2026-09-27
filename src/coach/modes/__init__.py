"""Modes are self-registering. Drop a .py file in this folder and it appears in --mode.

A mode module declares three things:

    HELP      str   one line, shown in --help
    ENDPOINT  str   "fast" for conversation (latency matters)
                    "deep" for analysis (quality matters, latency does not)
    async def run(endpoint, transcriber, speaker) -> list[dict]
                    endpoint bundles .client, .model and .extra for your ENDPOINT.
                    Drive the session; return the fluency scores you collected.
                    Raise nothing: audio.QuitRequested is caught for you at the edge.

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
