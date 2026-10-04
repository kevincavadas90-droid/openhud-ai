"""Tests for multi-vendor GPU detection (NVIDIA, AMD, Intel).

The parsers are pure, so we can exercise every detection path on any platform
without a real GPU. We also assert the "never invent data" contract: unknown
values are ``None``/absent and "GPU não detectada" is reported honestly.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="openhud-gpu-")
os.environ["OPENHUD_DATA_DIR"] = str(Path(_TMP) / "data")
os.environ["OPENHUD_WORKSPACE"] = str(Path(_TMP) / "workspace")
os.environ["OPENHUD_PASSWORD"] = "test-password"

from openhud.agent import gpu  # noqa: E402


# --------------------------------------------------------------------------
# vendor classification
# --------------------------------------------------------------------------
def test_vendor_of_amd_r7_240():
    # The user's exact card must classify as AMD.
    assert gpu.vendor_of("XFX R7 240 2GB DDR3") == "amd"
    assert gpu.vendor_of("AMD Radeon R7 240") == "amd"
    assert gpu.vendor_of("Radeon RX 580") == "amd"
    assert gpu.vendor_of("ATI Radeon HD 8570") == "amd"


def test_vendor_of_nvidia():
    assert gpu.vendor_of("NVIDIA GeForce RTX 3060") == "nvidia"
    assert gpu.vendor_of("GeForce GTX 970") == "nvidia"
    assert gpu.vendor_of("Quadro P4000") == "nvidia"


def test_vendor_of_intel():
    assert gpu.vendor_of("Intel(R) UHD Graphics 630") == "intel"
    assert gpu.vendor_of("Intel Iris Xe Graphics") == "intel"
    assert gpu.vendor_of("Intel(R) Arc(TM) A750 Graphics") == "intel"


def test_vendor_of_unknown():
    assert gpu.vendor_of("Microsoft Basic Display Adapter") == "unknown"
    assert gpu.vendor_of("") == "unknown"
    assert gpu.vendor_of(None) == "unknown"


def test_vendor_from_pci_id():
    assert gpu.vendor_from_pci_id("0x10de") == "nvidia"
    assert gpu.vendor_from_pci_id("0x1002") == "amd"
    assert gpu.vendor_from_pci_id("0x8086") == "intel"
    assert gpu.vendor_from_pci_id("0xffff") == "unknown"
    assert gpu.vendor_from_pci_id(None) == "unknown"


# --------------------------------------------------------------------------
# lspci parsing (Linux)
# --------------------------------------------------------------------------
def test_parse_lspci_amd_r7_240():
    text = (
        "00:02.0 VGA compatible controller [0300]: Intel Corporation HD Graphics 530 [8086:1912]\n"
        "01:00.0 VGA compatible controller [0300]: Advanced Micro Devices, Inc. [AMD/ATI] "
        "Oland [Radeon HD 8570 / R7 240] [1002:6613]\n"
        "03:00.0 3D controller [0302]: NVIDIA Corporation GP107M [GeForce GTX 1050 Ti Mobile] [10de:1c8c]\n"
        "00:1f.3 Audio device [0403]: Intel Corporation Sunrise Point-H HD Audio [8086:a170]\n"
    )
    gpus = gpu.parse_lspci(text)
    names = [g["name"] for g in gpus]
    vendors = [g["vendor"] for g in gpus]
    assert len(gpus) == 3  # audio device ignored
    assert "amd" in vendors and "nvidia" in vendors and "intel" in vendors
    assert any("R7 240" in n for n in names)


def test_parse_lspci_empty():
    assert gpu.parse_lspci("") == []
    assert gpu.parse_lspci("00:00.0 Host bridge: Intel Corporation") == []


# --------------------------------------------------------------------------
# Windows CIM parsing
# --------------------------------------------------------------------------
def test_parse_cim_amd_r7_240():
    text = (
        "Name                    : AMD Radeon R7 240\n"
        "AdapterRAM              : 2147483648\n"
        "DriverVersion           : 27.20.1034.2\n"
        "\n"
        "Name                    : Intel(R) HD Graphics 4600\n"
        "AdapterRAM              : 1073741824\n"
        "DriverVersion           : 20.19.15.4835\n"
        "\n"
    )
    gpus = gpu.parse_cim_video_controllers(text)
    assert len(gpus) == 2
    amd = next(g for g in gpus if g["vendor"] == "amd")
    assert amd["name"] == "AMD Radeon R7 240"
    assert amd["mem_total_mb"] == 2048  # 2 GB
    assert gpus[1]["vendor"] == "intel"


def test_parse_cim_never_invents_missing_fields():
    text = "Name                    : Microsoft Basic Display Adapter\n\n"
    gpus = gpu.parse_cim_video_controllers(text)
    assert len(gpus) == 1
    assert gpus[0]["vendor"] == "unknown"
    # No VRAM field must NOT become a fabricated number.
    assert "mem_total_mb" not in gpus[0]


def test_parse_cim_empty():
    assert gpu.parse_cim_video_controllers("") == []
    assert gpu.parse_cim_video_controllers("\n\n") == []


# --------------------------------------------------------------------------
# sysfs parsing (Linux) via a fake /sys tree
# --------------------------------------------------------------------------
def _make_sysfs(tmp: Path, vendor_id: str, *, vram_total: int | None = None,
                vram_used: int | None = None, busy: int | None = None,
                temp_milli: int | None = None) -> Path:
    card = tmp / "card0" / "device"
    (card / "hwmon" / "hwmon0").mkdir(parents=True)
    (card / "vendor").write_text(vendor_id + "\n")
    if vram_total is not None:
        (card / "mem_info_vram_total").write_text(str(vram_total))
    if vram_used is not None:
        (card / "mem_info_vram_used").write_text(str(vram_used))
    if busy is not None:
        (card / "gpu_busy_percent").write_text(str(busy))
    if temp_milli is not None:
        (card / "hwmon" / "hwmon0" / "temp1_input").write_text(str(temp_milli))
    return tmp


def test_sysfs_amd_identity_and_metrics(tmp_path, monkeypatch):
    _make_sysfs(tmp_path, "0x1002", vram_total=2 * 1024**3,
                vram_used=512 * 1024**2, busy=37, temp_milli=52000)
    monkeypatch.setattr(gpu.glob, "glob", lambda pat: (
        [str(tmp_path / "card0")] if pat.endswith("card[0-9]*") else
        [str(tmp_path / "card0" / "device" / "hwmon" / "hwmon0")] if "hwmon*" in pat else []))
    gpus = gpu.detect_linux_sysfs()
    assert len(gpus) == 1
    g = gpus[0]
    assert g["vendor"] == "amd"
    assert g["mem_total_mb"] == 2048
    assert g["mem_used_mb"] == 512
    assert g["util_percent"] == 37.0
    assert g["temp_c"] == 52.0


def test_sysfs_without_metrics_reports_none(tmp_path, monkeypatch):
    _make_sysfs(tmp_path, "0x8086")  # Intel, no metrics exposed
    monkeypatch.setattr(gpu.glob, "glob", lambda pat: (
        [str(tmp_path / "card0")] if pat.endswith("card[0-9]*") else []))
    gpus = gpu.detect_linux_sysfs()
    assert len(gpus) == 1
    g = gpus[0]
    assert g["vendor"] == "intel"
    assert "util_percent" not in g
    assert "mem_total_mb" not in g


# --------------------------------------------------------------------------
# merge logic
# --------------------------------------------------------------------------
def test_merge_keeps_all_vendors():
    base = [{"name": "NVIDIA GeForce RTX 3060", "vendor": "nvidia", "util_percent": 40}]
    extra = [{"name": "AMD Radeon R7 240", "vendor": "amd", "source": "cim"}]
    merged = gpu._merge(base, extra)
    assert len(merged) == 2
    assert {g["vendor"] for g in merged} == {"nvidia", "amd"}


def test_merge_dedupes_same_family():
    base = [{"name": "NVIDIA GeForce RTX 3060", "vendor": "nvidia"}]
    extra = [{"name": "NVIDIA GeForce RTX 3060", "vendor": "nvidia"}]
    assert len(gpu._merge(base, extra)) == 1


# --------------------------------------------------------------------------
# detect_gpus contract
# --------------------------------------------------------------------------
def test_detect_gpus_never_raises_and_returns_list():
    result = gpu.detect_gpus()
    assert isinstance(result, list)
    for g in result:
        assert "name" in g
        assert "vendor" in g
        # Never invent a metric: any present numeric must be a real number.
        for key in ("util_percent", "mem_used_mb", "mem_total_mb", "temp_c"):
            if key in g and g[key] is not None:
                assert isinstance(g[key], (int, float))


def test_telemetry_uses_multivendor_detection():
    from openhud.agent import telemetry

    metrics = telemetry.TelemetryCollector().collect()
    assert isinstance(metrics.get("gpu"), list)


def test_selfcheck_gpu_identity_only_is_warning(monkeypatch):
    """When only the identity is known (no live metrics), it must be WARNING."""
    from openhud.agent import selfcheck

    fake = {"available": True, "cpu": {}, "ram": {}, "disk": [],
            "gpu": [{"name": "AMD Radeon R7 240", "vendor": "amd"}]}

    class _C:
        def collect(self):
            return fake

    monkeypatch.setattr(__import__("openhud.agent.telemetry", fromlist=["TelemetryCollector"]),
                        "TelemetryCollector", _C)
    rep = selfcheck.Report(platform="Windows 10")
    selfcheck.check_gpu(rep)
    entry = next(c for c in rep.checks if c.name == "GPU")
    assert entry.status == selfcheck.WARNING
    assert "R7 240" in entry.detail


def test_selfcheck_gpu_no_gpu_is_honest(monkeypatch):
    from openhud.agent import selfcheck

    fake = {"available": True, "cpu": {}, "ram": {}, "disk": [], "gpu": []}

    class _C:
        def collect(self):
            return fake

    monkeypatch.setattr(__import__("openhud.agent.telemetry", fromlist=["TelemetryCollector"]),
                        "TelemetryCollector", _C)
    rep = selfcheck.Report(platform="Windows 10")
    selfcheck.check_gpu(rep)
    entry = next(c for c in rep.checks if c.name == "GPU")
    assert entry.status in (selfcheck.WARNING, selfcheck.NOT_INSTALLED)
    assert "não detectada" in entry.detail.lower()


def test_selfcheck_gpu_with_metrics_is_pass(monkeypatch):
    from openhud.agent import selfcheck

    fake = {"available": True, "cpu": {}, "ram": {}, "disk": [],
            "gpu": [{"name": "NVIDIA GeForce RTX 3060", "vendor": "nvidia",
                     "util_percent": 12.0, "mem_used_mb": 1024, "mem_total_mb": 12288}]}

    class _C:
        def collect(self):
            return fake

    monkeypatch.setattr(__import__("openhud.agent.telemetry", fromlist=["TelemetryCollector"]),
                        "TelemetryCollector", _C)
    rep = selfcheck.Report(platform="Windows 10")
    selfcheck.check_gpu(rep)
    entry = next(c for c in rep.checks if c.name == "GPU")
    assert entry.status == selfcheck.PASS
    assert "RTX 3060" in entry.detail
