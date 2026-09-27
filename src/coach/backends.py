"""What can play the interviewer, and what each one costs you.

Latency marked "measured" was timed against this machine. Everything marked "est." is
extrapolated from published benchmarks on an M3 Pro 18GB and should be treated as a guess.
ponytail: the app knows its real first-token times - record medians here if the guesses
annoy you.
"""

import socket
from typing import NamedTuple
from urllib.request import urlopen

from . import settings


class Backend(NamedTuple):
    key: str
    label: str
    model: str
    roles: tuple  # "fast" = conversation, "deep" = analysis
    latency: str
    cost: str
    free: bool
    ram: str
    note: str
    local: bool = True
    extra: dict | None = None  # thinking flags travel with the model, never globally


# Credentials are not here on purpose: llm.endpoint_for resolves them from settings at
# use time, so editing the API key in the UI works without a restart.
CLOUD = {"local": False}

# A data table: column alignment reads better here than one argument per line.
# fmt: off
#        key             label                    model                        roles            latency          cost        free   ram       note
CATALOGUE: list[Backend] = [
    # ---- cloud ----
    Backend("flash-lite",    "Gemini 3.5 Flash-Lite", "gemini-3.5-flash-lite",     ("fast",),        "1.1s measured", "$0.42/mo", False, "cloud",  "best conversation latency; free tier covers an hour a day", **CLOUD),
    Backend("flash",         "Gemini 3.8 Flash",      "gemini-3.8-flash",          ("fast", "deep"), "3-9s measured", "$1.08/mo", False, "cloud",  "smartest option here; thinking stays on", **CLOUD),

    # ---- local: conversation ----
    Backend("lfm2.5",        "LFM2.5 1.2B",           "liquid/lfm2.5-1.2b",        ("fast",),        "<0.5s est.",    "free",     True,  "0.95GB", "emergency fallback; fastest, weakest, no reasoning"),
    Backend("ministral3",    "Ministral 3 3B",        "mistralai/ministral-3-3b",  ("fast",),        "~0.6s est.",    "free",     True,  "2GB",    "Apache 2.0, light and chatty; no reasoning mode"),
    Backend("gemma4-e2b",    "Gemma 4 E2B",           "google/gemma-4-e2b",        ("fast",),        "~0.6s est.",    "free",     True,  "4GB",    "effective 2B, reasoning toggle, 128K context"),
    Backend("nemotron-nano", "Nemotron 3 Nano 4B",    "nvidia/nemotron-3-nano-4b", ("fast",),        "~0.8s est.",    "free",     True,  "5GB",    "hybrid Mamba2; cheap long context, 256K"),
    Backend("gemma4-e4b",    "Gemma 4 E4B",           "google/gemma-4-e4b",        ("fast", "deep"), "~1s est.",      "free",     True,  "6GB",    "effective 4B, reasoning; good offline all-rounder"),

    # ---- local: analysis ----
    Backend("bonsai27",      "Bonsai 27B (ternary)",  "prism-ml/bonsai-27b",       ("deep",),        "~3-5s est.",    "free",     True,  "4GB",    "27B reasoning compressed to ~4GB, keeps 94.6% of FP16 - best offline review"),
    Backend("qwen3.5-9b",    "Qwen3.5 9B",            "qwen/qwen3.5-9b",           ("deep",),        "~2-3s est.",    "free",     True,  "7GB",    "dense 9B reasoner, 262K context; too slow to converse with"),
    Backend("gpt-oss-20b",   "gpt-oss-20B",           "openai/gpt-oss-20b",        ("deep",),        "~2-3s est.",    "free",     True,  "12GB",   "21B MoE, 3.6B active, ~21 tok/s here; tight on 18GB alongside Whisper"),
]
# fmt: on

BY_KEY = {b.key: b for b in CATALOGUE}


def online(timeout: float = 2.0) -> bool:
    """Is the cloud endpoint actually reachable right now?"""
    try:
        socket.create_connection(("generativelanguage.googleapis.com", 443), timeout).close()
        return True
    except OSError:
        return False


def lm_studio_models(timeout: float = 1.5) -> set[str]:
    """Model ids LM Studio is serving. Empty set if it isn't running."""
    try:
        import json

        url = settings.get("lm_studio_url")
        with urlopen(f"{url}/models", timeout=timeout) as response:
            return {m["id"] for m in json.load(response).get("data", [])}
    except Exception:
        return set()


def survey(role: str) -> tuple[list[tuple[Backend, str | None]], bool]:
    """Backends suited to `role`, each with a reason it is unusable (or None).

    Returns (rows, any_available).
    """
    has_net = online()
    local_models = lm_studio_models()
    rows = []
    for backend in CATALOGUE:
        if role not in backend.roles:
            continue
        if backend.local:
            if not local_models:
                reason = "LM Studio not running"
            elif backend.model not in local_models:
                reason = "not loaded in LM Studio"
            else:
                reason = None
        else:
            reason = None if has_net else "no internet"
            if reason is None and not settings.api_key():
                reason = "no API key - add one in Settings"
        rows.append((backend, reason))
    return rows, any(reason is None for _, reason in rows)
