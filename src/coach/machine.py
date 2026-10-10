"""This computer, and how big a local model it can hold.

A model LM Studio loads has to fit in the memory the GPU may use, beside Whisper, Kokoro,
the browser and the system. One that does not either fails to load or makes the whole
machine swap mid-sentence, so a model too big for it is never suggested.
"""

import functools
import os
import pathlib
import platform
import subprocess

GIB = 2**30
# What everything but the model needs: the system, the browser, Whisper and Kokoro. A
# calibration knob: on 18GB it leaves 12GB, where gpt-oss-20b's 12GB was "tight".
RESERVED_GB = 6
# Of unified memory, macOS lets the GPU use about two thirds, and three quarters from 36GB.
GPU_SHARE = (2 / 3, 3 / 4)


def _sysctl(name: str) -> str:
    try:
        found = subprocess.run(  # noqa: S603 - a fixed command, no input from anyone
            ["/usr/sbin/sysctl", "-n", name], capture_output=True, text=True, timeout=2, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return found.stdout.strip()


def _cpu() -> str:
    if platform.system() == "Darwin":
        return _sysctl("machdep.cpu.brand_string") or platform.machine()
    try:
        text = pathlib.Path("/proc/cpuinfo").read_text(encoding="utf-8")
    except OSError:
        return platform.processor() or platform.machine()
    names = [line.split(":", 1)[1].strip() for line in text.splitlines() if "model name" in line]
    return names[0] if names else platform.machine()


@functools.cache
def specs() -> dict:
    """The chip, its cores, its memory, and how much of that a model can have.

    ponytail: an NVIDIA card's own memory is not read, and in Docker this is the VM's
    memory, not the host's where LM Studio runs; read nvidia-smi, or take the figure from
    the environment, when someone runs either.
    """
    ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / GIB
    unified = platform.system() == "Darwin" and platform.machine() == "arm64"
    room = ram - RESERVED_GB
    if unified:
        room = min(room, ram * GPU_SHARE[ram >= 36])
    return {
        "cpu": _cpu(),
        "cores": os.cpu_count() or 0,
        "ram_gb": round(ram),
        "unified": unified,  # the GPU shares the RAM: Apple silicon
        "model_gb": max(0, round(room)),
    }
