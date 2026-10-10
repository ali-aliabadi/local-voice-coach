"""This computer, and which local models it can hold."""

import json
from typing import NamedTuple

import pytest

from coach import backends, machine, settings

READ = machine.specs  # the real one: conftest swaps it for a fixed machine in every test

EVERY_LOCAL = {b.model for b in backends.CATALOGUE if b.local}


def test_this_machine_is_read():
    found = READ()
    assert found["cpu"]
    assert found["cores"] > 0
    assert 0 <= found["model_gb"] < found["ram_gb"]


APPLE = {"_name": "Apple M3 Pro", "sppci_model": "Apple M3 Pro", "sppci_cores": "14"}
INTEL_GPU = {"sppci_model": "Intel UHD Graphics 630", "spdisplays_vram": "1536 MB"}
RADEON = {"sppci_model": "AMD Radeon Pro 5500M", "spdisplays_vram": "8 GB"}


def profiler(*cards):
    return {"system_profiler": json.dumps({"SPDisplaysDataType": list(cards)})}


class Box(NamedTuple):
    """A machine to pretend to be: what each tool says on it, and an AMD card's memory."""

    system: str
    arch: str
    ram: float
    tools: dict
    card_gb: int = 0


@pytest.mark.parametrize(
    ("box", "gpu", "room"),
    [
        (Box("Darwin", "arm64", 18, profiler(APPLE)), "Apple M3 Pro", 12),
        (Box("Darwin", "arm64", 64, profiler(APPLE)), "Apple M3 Pro", 48),  # three quarters
        (Box("Darwin", "arm64", 64, {**profiler(APPLE), "sysctl": "57344"}), "Apple M3 Pro", 56),
        (Box("Darwin", "x86_64", 32, profiler(INTEL_GPU, RADEON)), "AMD Radeon Pro 5500M", 7),
        (Box("Darwin", "x86_64", 16, profiler(INTEL_GPU)), None, 10),  # too small: the CPU
        (Box("Linux", "x86_64", 64, {"nvidia-smi": "NVIDIA GeForce RTX 4090, 24564\n"}),
         "NVIDIA GeForce RTX 4090", 23),
        (Box("Linux", "x86_64", 64, {"nvidia-smi": "NVIDIA RTX A4000, 16376\n" * 2}),
         "NVIDIA RTX A4000 x2", 31),
        (Box("Linux", "x86_64", 32, {}, card_gb=16), "AMD GPU", 15),
        (Box("Linux", "x86_64", 32, {}), None, 26),  # no GPU: on the CPU, from RAM
    ],
)  # fmt: skip
def test_how_big_a_model_fits_is_read_from_the_hardware(monkeypatch, tmp_path, box, gpu, room):
    monkeypatch.setattr(machine.platform, "system", lambda: box.system)
    monkeypatch.setattr(machine.platform, "machine", lambda: box.arch)
    monkeypatch.setattr(machine, "_ram_gb", lambda: box.ram)
    monkeypatch.setattr(machine, "_run", lambda *command: box.tools.get(command[0], ""))
    monkeypatch.setattr(machine, "DRM", tmp_path)
    if box.card_gb:
        (tmp_path / "card0" / "device").mkdir(parents=True)
        (tmp_path / "card0/device/mem_info_vram_total").write_text(str(box.card_gb * machine.GIB))
    found = READ.__wrapped__()  # past the cache
    assert (found["gpu"] or {}).get("name") == gpu
    assert found["model_gb"] == room


def test_lm_studio_on_another_machine_is_not_measured_by_this_one(monkeypatch):
    """From inside Docker, LM Studio is on the host: the container's memory says nothing."""
    small_machine(monkeypatch)
    settings.set("lm_studio_url", "http://host.docker.internal:1234/v1")
    assert machine.room() is None
    assert backends.too_big(backends.BY_KEY["gpt-oss-20b"]) is None


def small_machine(monkeypatch, room: int = 4) -> None:
    monkeypatch.setattr(machine, "specs", lambda: {"model_gb": room})
    monkeypatch.setattr(backends, "lm_studio_models", lambda _timeout=1.5: EVERY_LOCAL)


def test_a_model_too_big_is_offered_greyed_out_and_says_why(monkeypatch):
    small_machine(monkeypatch)
    rows, _ = backends.survey("deep")
    why = {backend.key: reason for backend, reason in rows}
    assert why["gpt-oss-20b"] == "needs 12GB, this machine can spare 4GB"
    assert why["bonsai27"] is None, "loaded, and it fits"


def test_a_model_too_big_never_stands_in(monkeypatch):
    small_machine(monkeypatch)
    assert backends.stand_in() is backends.BY_KEY["bonsai27"]
    small_machine(monkeypatch, room=1)
    assert backends.stand_in() is backends.BY_KEY["lfm2.5"], "the only one that fits"
    small_machine(monkeypatch, room=0)
    assert backends.stand_in() is None


def test_settings_offer_what_fits_and_keep_what_was_chosen(monkeypatch):
    small_machine(monkeypatch)
    offered = backends.choices("qwen3.5-9b")
    assert "flash" in offered, "a cloud model fits anywhere"
    assert "qwen3.5-9b" in offered, "chosen before: a select must still show it"
    assert "gpt-oss-20b" not in offered
