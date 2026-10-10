"""This computer, and how big a local model it can hold. Read from the machine itself.

Where a model runs decides how big it can be. Apple silicon's GPU shares the RAM; an
NVIDIA or AMD card has memory of its own; with neither, the model runs on the CPU from
RAM. Whatever it runs on, it has to fit beside Whisper, Kokoro, the browser and the
system, or LM Studio fails to load it or the machine swaps mid-sentence.
"""

import functools
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
from typing import NamedTuple
from urllib.parse import urlsplit

from . import settings

GIB = 2**30
# Calibration knobs, not facts: what everything but the model needs (the system, the
# browser, Whisper and Kokoro), and what a model's context needs beside its weights on a
# card of its own.
RESERVED_GB = 6
CONTEXT_GB = 1
# Of unified memory, macOS lets the GPU use about two thirds, and three quarters from 36GB,
# unless iogpu.wired_limit_mb was raised by hand.
GPU_SHARE = (2 / 3, 3 / 4)
SMALLEST_CARD_GB = 2  # less is an integrated GPU's carve-out, of no use to a model
HERE = ("localhost", "127.0.0.1", "::1")
DRM = pathlib.Path("/sys/class/drm")  # where Linux lists graphics cards


class Gpu(NamedTuple):
    name: str
    gb: float  # its own memory; 0 when it shares the RAM
    cores: int = 0  # only Apple reports them


def _run(*command: str) -> str:
    """A tool's output, or "" if it is not installed here or fails."""
    path = shutil.which(command[0])
    if not path:
        return ""
    try:
        done = subprocess.run(  # noqa: S603 - fixed commands, no input from anyone
            [path, *command[1:]], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout


def _gb(text: str) -> float:
    """ "8 GB" or "1536 MB", as macOS writes a card's memory, in GB."""
    found = re.match(r"([\d.]+)\s*([GM])B", text)
    return float(found[1]) / (1 if found[2] == "G" else 1024) if found else 0.0


def _nvidia() -> Gpu | None:
    query = ("--query-gpu=name,memory.total", "--format=csv,noheader,nounits")
    cards = [line.rsplit(",", 1) for line in _run("nvidia-smi", *query).splitlines() if "," in line]
    if not cards:
        return None
    more = f" x{len(cards)}" if len(cards) > 1 else ""  # LM Studio splits a model across them
    return Gpu(cards[0][0].strip() + more, sum(float(mib) for _, mib in cards) / 1024)


def _mac() -> Gpu | None:
    try:
        cards = json.loads(_run("system_profiler", "SPDisplaysDataType", "-json"))
        found = [
            Gpu(c.get("sppci_model", "GPU"), _gb(c.get("spdisplays_vram", "")),
                int(c.get("sppci_cores", "0")) if str(c.get("sppci_cores", "")).isdigit() else 0)
            for c in cards["SPDisplaysDataType"]
        ]  # fmt: skip
    except (ValueError, KeyError, TypeError):
        return None
    return max(found, key=lambda g: (g.gb, g.cores), default=None)


def _amd() -> Gpu | None:
    """An AMD card on Linux: the amdgpu driver says how much memory it has."""
    sizes = []
    for path in DRM.glob("card*/device/mem_info_vram_total"):
        try:
            sizes.append(int(path.read_text()) / GIB)
        except (OSError, ValueError):
            continue
    return Gpu("AMD GPU", max(sizes)) if sizes else None


def _gpu(unified: bool) -> Gpu | None:
    """The GPU a model can run on, or None if there is none worth using."""
    gpu = _nvidia() or (_mac() if platform.system() == "Darwin" else _amd())
    if gpu and (unified or gpu.gb >= SMALLEST_CARD_GB):
        return gpu
    return None


def _cpu() -> str:
    if platform.system() == "Darwin":
        return _run("sysctl", "-n", "machdep.cpu.brand_string").strip() or platform.machine()
    try:
        text = pathlib.Path("/proc/cpuinfo").read_text(encoding="utf-8")
    except OSError:
        return platform.processor() or platform.machine()
    names = [line.split(":", 1)[1].strip() for line in text.splitlines() if "model name" in line]
    return names[0] if names else platform.machine()


def _ram_gb() -> float:
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / GIB


def _room(ram: float, gpu: Gpu | None, unified: bool) -> float:
    """The biggest model that runs well: on the GPU if there is one, else on the CPU."""
    if gpu and not unified:
        return gpu.gb - CONTEXT_GB
    if unified:
        wired = _run("sysctl", "-n", "iogpu.wired_limit_mb").strip()
        limit = int(wired) / 1024 if wired.isdigit() and int(wired) else 0
        return min(ram - RESERVED_GB, limit or ram * GPU_SHARE[ram >= 36])
    return ram - RESERVED_GB


@functools.cache
def specs() -> dict:
    """The CPU, its cores, the RAM, the GPU a model can use, and how big a model fits."""
    ram = _ram_gb()
    unified = platform.system() == "Darwin" and platform.machine() == "arm64"
    gpu = _gpu(unified)
    return {
        "cpu": _cpu(),
        "cores": os.cpu_count() or 0,
        "ram_gb": round(ram),
        "unified": unified,  # Apple silicon: the GPU shares the RAM
        "gpu": {"name": gpu.name, "gb": round(gpu.gb), "cores": gpu.cores} if gpu else None,
        "model_gb": max(0, round(_room(ram, gpu, unified))),
    }


def lm_studio_host() -> str:
    return urlsplit(str(settings.get("lm_studio_url"))).hostname or ""


def room() -> int | None:
    """How big a model LM Studio can hold, in GB. None when LM Studio runs on another
    machine - the host, from inside Docker - whose memory this one cannot see."""
    return specs()["model_gb"] if lm_studio_host() in HERE else None
