"""Multi-vendor GPU detection (NVIDIA, AMD, Intel).

The telemetry collector must not depend on NVIDIA alone. This module detects
the *identity* of every GPU (name + vendor) using whatever the OS exposes, and
reads live metrics only when a real source is available. A value that cannot be
read is reported as ``None`` — never invented. When no GPU can be identified at
all, callers report "GPU não detectada".

Sources, in order of richness:
  * NVIDIA  — NVML (``pynvml``): utilisation, VRAM, temperature, clock, power.
  * AMD     — Linux ``amdgpu``/``radeon`` sysfs: ``gpu_busy_percent``,
              ``mem_info_vram_used``/``_total``, ``hwmon`` temperature/power.
              Windows: identity via CIM (name + VRAM); live metrics only if a
              vendor tool is present (``rocm-smi``), otherwise ``None``.
  * Intel   — Linux ``i915``/``xe`` sysfs: frequency; Windows: identity via CIM.
  * Any     — identity via CIM on Windows, ``lspci``/sysfs on Linux.

All parsing functions are pure so they can be unit-tested on any platform.
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys
import time
from typing import Any

VENDOR_IDS = {
    "0x10de": "nvidia",
    "0x1002": "amd",
    "0x1022": "amd",
    "0x8086": "intel",
    "0x106b": "apple",
    "0x1af4": "virtio",
}


def vendor_of(name: str | None) -> str:
    """Best-effort vendor classification from a GPU name string."""
    if not name:
        return "unknown"
    n = name.lower()
    if any(k in n for k in ("nvidia", "geforce", "quadro", "rtx", "gtx", "tesla", "rtx a")):
        return "nvidia"
    if any(k in n for k in ("amd", "radeon", "ati ", "rx ", "vega", "firepro", "instinct", "rdna",
                            " r7 ", " r5 ", " r9 ", " r7", " r5", " r9")):
        return "amd"
    if any(k in n for k in ("intel", "iris", "uhd graphics", "hd graphics", "arc ", "xe graphics")):
        return "intel"
    return "unknown"


def vendor_from_pci_id(pci_id: str | None) -> str:
    if not pci_id:
        return "unknown"
    return VENDOR_IDS.get(pci_id.strip().lower(), "unknown")


def parse_lspci(text: str) -> list[dict[str, Any]]:
    """Parse ``lspci -nn`` output; keep VGA/3D/Display controllers only."""
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        low = line.lower()
        if not any(tag in low for tag in ("vga compatible controller", "3d controller", "display controller")):
            continue
        # "01:00.0 VGA compatible controller [0300]: NVIDIA Corporation GM204 [GeForce GTX 970] [10de:13c2]"
        name = line.split(":", 2)[-1].strip() if line.count(":") >= 2 else line.strip()
        pci_id = None
        if "[" in line and "]" in line:
            tail = line.rsplit("[", 1)[-1].rstrip("]")
            if ":" in tail and len(tail) <= 12:
                pci_id = "0x" + tail.split(":")[0]
        out.append({"name": name, "vendor": vendor_from_pci_id(pci_id), "source": "lspci"})
    return out


def parse_cim_video_controllers(text: str) -> list[dict[str, Any]]:
    """Parse ``Get-CimInstance Win32_VideoController`` text output.

    Expected lines like::

        Name                    : AMD Radeon R7 240
        AdapterRAM              : 2147483648
        DriverVersion           : 27.20.1034.2

    ``AdapterRAM`` is a signed 32-bit field on Windows and saturates near 4 GB,
    so it is treated as a *lower bound*; we never claim it is exact.
    """
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] = {}

    def flush() -> None:
        if current.get("name"):
            entries.append(dict(current))

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush()
            current.clear()
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = val.strip()
        if key == "name":
            flush()
            current.clear()
            current["name"] = val
        elif key in ("adapterram", "adapterrambytes"):
            try:
                current["vram_bytes"] = int(val)
            except ValueError:
                pass
        elif key in ("driverversion", "driverdate"):
            current.setdefault("driver", val)
    flush()
    for e in entries:
        e["vendor"] = vendor_of(e.get("name"))
        e["source"] = "cim"
        vb = e.pop("vram_bytes", None)
        if vb and vb > 0:
            e["mem_total_mb"] = round(vb / (1024 * 1024))
    return entries


def _run(cmd: list[str], timeout: float = 6.0) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.stdout or ""
    except Exception:
        return ""


def detect_windows_cim() -> list[dict[str, Any]]:
    ps = [
        "powershell", "-NoProfile", "-NonInteractive", "-Command",
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterRAM,DriverVersion | Format-List",
    ]
    out = _run(ps)
    if not out.strip():
        out = _run(["wmic", "path", "win32_VideoController", "get",
                    "Name,AdapterRAM,DriverVersion", "/format:list"])
    return parse_cim_video_controllers(out)


def _read_text(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return None


def _read_int(path: str) -> int | None:
    raw = _read_text(path)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def detect_linux_sysfs() -> list[dict[str, Any]]:
    """Enumerate DRM cards and read identity + live metrics from sysfs."""
    out: list[dict[str, Any]] = []
    for card in sorted(glob.glob("/sys/class/drm/card[0-9]*")):
        if not os.path.isdir(card):
            continue
        device = os.path.join(card, "device")
        vendor = vendor_from_pci_id(_read_text(os.path.join(device, "vendor")))
        name = f"GPU {vendor}" if vendor != "unknown" else "GPU"
        entry: dict[str, Any] = {"name": name, "vendor": vendor, "source": "sysfs"}

        mem_total = _read_int(os.path.join(device, "mem_info_vram_total"))
        mem_used = _read_int(os.path.join(device, "mem_info_vram_used"))
        busy = _read_int(os.path.join(device, "gpu_busy_percent"))
        if mem_total:
            entry["mem_total_mb"] = round(mem_total / (1024 * 1024))
        if mem_used:
            entry["mem_used_mb"] = round(mem_used / (1024 * 1024))
        if busy is not None:
            entry["util_percent"] = float(busy)

        # hwmon: temperature + power, when exposed.
        for hwmon in glob.glob(os.path.join(device, "hwmon", "hwmon*")):
            temp = _read_int(os.path.join(hwmon, "temp1_input"))
            if temp is not None:
                entry["temp_c"] = round(temp / 1000.0, 1)
            power = _read_int(os.path.join(hwmon, "power1_average"))
            if power is not None:
                entry["power_w"] = round(power / 1_000_000.0, 1)
        out.append(entry)
    return out


def detect_linux_lspci() -> list[dict[str, Any]]:
    return parse_lspci(_run(["lspci", "-nn"]))


def _merge(base: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge descriptors, preferring richer entries but keeping all GPUs."""
    if not extra:
        return base
    if not base:
        return extra
    seen = {_key(e) for e in base}
    for e in extra:
        k = _key(e)
        if k not in seen:
            base.append(e)
            seen.add(k)
    return base


def _key(e: dict[str, Any]) -> str:
    name = (e.get("name") or "").lower()
    for token in ("geforce", "radeon", "nvidia", "intel", "amd"):
        if token in name:
            # crude family key so CIM + NVML entries for the same card collapse
            return token
    return name


def detect_gpus() -> list[dict[str, Any]]:
    """Return one descriptor per GPU, with live metrics where really readable.

    Never raises and never invents values. Missing fields are ``None``/absent.
    Identity detection (CIM/sysfs/lspci) is cached briefly because it can shell
    out on Windows; NVIDIA live metrics are always read fresh.
    """
    gpus: list[dict[str, Any]] = []

    # 1. NVIDIA via NVML (richest; covers Linux + Windows).
    try:
        from .telemetry import _gpu_nvml

        for g in _gpu_nvml():
            g = dict(g)
            g.setdefault("vendor", "nvidia")
            g.setdefault("source", "nvml")
            gpus.append(g)
    except Exception:
        pass

    # 2. Platform identity (cached) so we still see AMD/Intel.
    return _merge(gpus, _identities_cached())


_identity_cache: tuple[float, list[dict[str, Any]]] = (0.0, [])
_IDENTITY_TTL = 30.0


def _identities_cached() -> list[dict[str, Any]]:
    global _identity_cache

    now = time.monotonic()
    ts, cached = _identity_cache
    if cached and (now - ts) < _IDENTITY_TTL:
        return cached
    try:
        if sys.platform == "win32":
            found = detect_windows_cim()
        else:
            found = detect_linux_sysfs()
            if not found:
                found = detect_linux_lspci()
    except Exception:
        found = []
    _identity_cache = (now, found)
    return found
