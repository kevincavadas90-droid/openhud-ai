"""Hardware telemetry collector.

Collects real metrics with psutil, plus GPU metrics via NVML when an NVIDIA
GPU and driver are present. Every field is best-effort: when a value cannot be
read on the current machine it is reported as ``None`` rather than invented,
so the UI and the diagnostics engine can tell "0%" from "unknown".

The same module runs inside the OpenHUD Agent on the user's PC and inside the
server (for the local/demo device), so both paths use identical, tested code.
"""
from __future__ import annotations

import platform
import socket
import time
from typing import Any

try:  # psutil is a hard dependency of the agent, optional on the server
    import psutil
except Exception:  # pragma: no cover - exercised only without psutil
    psutil = None  # type: ignore

# --------------------------------------------------------------------------
# GPU via NVML (NVIDIA). Loaded lazily; absence is normal and not an error.
# --------------------------------------------------------------------------
_nvml = None
_nvml_ready = False


def _init_nvml() -> bool:
    global _nvml, _nvml_ready
    if _nvml_ready:
        return _nvml is not None
    _nvml_ready = True
    try:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import pynvml  # type: ignore

            pynvml.nvmlInit()
        _nvml = pynvml
    except Exception:
        _nvml = None
    return _nvml is not None


def _gpu_nvml() -> list[dict[str, Any]]:
    if not _init_nvml():
        return []
    out: list[dict[str, Any]] = []
    assert _nvml is not None
    try:
        count = _nvml.nvmlDeviceGetCount()
    except Exception:
        return []
    for i in range(count):
        try:
            h = _nvml.nvmlDeviceGetHandleByIndex(i)
            name = _nvml.nvmlDeviceGetName(h)
            if isinstance(name, bytes):
                name = name.decode("utf-8", "replace")
            util = _nvml.nvmlDeviceGetUtilizationRates(h)
            mem = _nvml.nvmlDeviceGetMemoryInfo(h)
            entry: dict[str, Any] = {
                "index": i,
                "name": name,
                "util_percent": float(util.gpu),
                "mem_used_mb": round(mem.used / (1024 * 1024), 1),
                "mem_total_mb": round(mem.total / (1024 * 1024), 1),
                "mem_percent": round(100.0 * mem.used / mem.total, 1) if mem.total else None,
            }
            try:
                entry["temp_c"] = float(_nvml.nvmlDeviceGetTemperature(h, _nvml.NVML_TEMPERATURE_GPU))
            except Exception:
                entry["temp_c"] = None
            try:
                entry["clock_mhz"] = float(_nvml.nvmlDeviceGetClockInfo(h, _nvml.NVML_CLOCK_GRAPHICS))
            except Exception:
                entry["clock_mhz"] = None
            try:
                entry["power_w"] = round(_nvml.nvmlDeviceGetPowerUsage(h) / 1000.0, 1)
            except Exception:
                entry["power_w"] = None
            out.append(entry)
        except Exception:
            continue
    return out


def _cpu_temp() -> float | None:
    if psutil is None:
        return None
    fn = getattr(psutil, "sensors_temperatures", None)
    if not fn:
        return None
    try:
        temps = fn()
    except Exception:
        return None
    for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz", "zenpower"):
        if key in temps and temps[key]:
            for entry in temps[key]:
                if entry.current:
                    return float(entry.current)
    for entries in temps.values():
        for entry in entries:
            if entry.current:
                return float(entry.current)
    return None


def _net_rate(prev: dict[str, Any] | None, interval: float) -> dict[str, float]:
    if psutil is None:
        return {"up_kbps": 0.0, "down_kbps": 0.0}
    io = psutil.net_io_counters()
    if prev is None or interval <= 0:
        return {"up_kbps": 0.0, "down_kbps": 0.0}
    up = (io.bytes_sent - prev["bytes_sent"]) * 8 / 1000.0 / interval
    down = (io.bytes_recv - prev["bytes_recv"]) * 8 / 1000.0 / interval
    return {"up_kbps": round(up, 1), "down_kbps": round(down, 1)}


class TelemetryCollector:
    """Stateful collector: call ``collect()`` repeatedly for rates."""

    def __init__(self, top_processes: int = 8) -> None:
        self.top_processes = top_processes
        self._prev_net: dict[str, Any] | None = None
        self._prev_at: float = 0.0
        # Prime cpu_percent so the first real reading is not 0.
        if psutil is not None:
            try:
                psutil.cpu_percent(interval=None)
            except Exception:
                pass

    def system_info(self) -> dict[str, Any]:
        if psutil is None:
            return {"os": platform.platform(), "hostname": socket.gethostname()}
        return {
            "os": f"{platform.system()} {platform.release()}",
            "platform": platform.platform(),
            "hostname": socket.gethostname(),
            "arch": platform.machine(),
            "python": platform.python_version(),
            "cpu_name": platform.processor() or None,
            "cores_physical": psutil.cpu_count(logical=False),
            "cores_logical": psutil.cpu_count(logical=True),
            "ram_total_mb": round(psutil.virtual_memory().total / (1024 * 1024), 1),
            "boot_time": psutil.boot_time(),
        }

    def collect(self) -> dict[str, Any]:
        now = time.time()
        if psutil is None:
            return {"ts": now, "available": False}

        cpu_percent = psutil.cpu_percent(interval=None)
        try:
            freq = psutil.cpu_freq()
            cpu_freq = round(freq.current, 1) if freq else None
        except Exception:
            cpu_freq = None
        try:
            per_core = psutil.cpu_percent(interval=None, percpu=True)
        except Exception:
            per_core = []

        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()

        disk: list[dict[str, Any]] = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except Exception:
                continue
            disk.append(
                {
                    "mount": part.mountpoint,
                    "device": part.device,
                    "percent": usage.percent,
                    "used_gb": round(usage.used / (1024**3), 1),
                    "total_gb": round(usage.total / (1024**3), 1),
                    "free_gb": round(usage.free / (1024**3), 1),
                }
            )
        try:
            dio = psutil.disk_io_counters()
            disk_io = {"read_mb": round(dio.read_bytes / (1024**2), 1), "write_mb": round(dio.write_bytes / (1024**2), 1)} if dio else {}
        except Exception:
            disk_io = {}

        net_io = None
        try:
            net_io = psutil.net_io_counters()
        except Exception:
            net_io = None
        interval = now - self._prev_at
        prev_snapshot = self._prev_net
        rates = _net_rate(prev_snapshot, interval) if prev_snapshot is not None else {"up_kbps": 0.0, "down_kbps": 0.0}
        if net_io is not None:
            self._prev_net = {"bytes_sent": net_io.bytes_sent, "bytes_recv": net_io.bytes_recv}
            self._prev_at = now

        procs: list[dict[str, Any]] = []
        try:
            for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "username"]):
                info = p.info
                if info.get("cpu_percent") is None and info.get("memory_percent") is None:
                    continue
                procs.append(
                    {
                        "pid": info.get("pid"),
                        "name": info.get("name"),
                        "cpu_percent": round(info.get("cpu_percent") or 0.0, 1),
                        "memory_percent": round(info.get("memory_percent") or 0.0, 1),
                        "username": info.get("username"),
                    }
                )
            procs.sort(key=lambda x: (x["cpu_percent"], x["memory_percent"]), reverse=True)
            procs = procs[: self.top_processes]
        except Exception:
            procs = []

        gpus = _gpu_nvml()

        return {
            "ts": now,
            "available": True,
            "cpu": {
                "percent": round(cpu_percent, 1),
                "freq_mhz": cpu_freq,
                "per_core": [round(x, 1) for x in per_core],
                "temp_c": _cpu_temp(),
                "cores_physical": psutil.cpu_count(logical=False),
                "cores_logical": psutil.cpu_count(logical=True),
                "load_avg": list(psutil.getloadavg()) if hasattr(psutil, "getloadavg") else None,
            },
            "ram": {
                "percent": vm.percent,
                "used_mb": round(vm.used / (1024 * 1024), 1),
                "total_mb": round(vm.total / (1024 * 1024), 1),
                "available_mb": round(vm.available / (1024 * 1024), 1),
                "swap_percent": sm.percent,
            },
            "gpu": gpus,
            "disk": disk,
            "disk_io": disk_io,
            "network": rates,
            "processes": procs,
            "process_count": len(psutil.pids()),
        }
