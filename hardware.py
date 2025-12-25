import platform
import subprocess
from typing import List

import platform
import subprocess
from typing import Dict, List

import psutil

HARDWARE_CACHE: Dict[str, str] = {}


def _get_cpu_model() -> str:
    cpu_name = platform.processor()
    if cpu_name and "Family" not in cpu_name and "Model" not in cpu_name:
        return cpu_name
    try:
        output = subprocess.check_output(
            ["wmic", "cpu", "get", "Name"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        lines: List[str] = [line.strip() for line in output.splitlines() if line.strip()]
        filtered = [line for line in lines if line.lower() != "name"]
        if filtered:
            return filtered[0]
    except Exception:
        pass
    return cpu_name or "Unknown CPU"


def _get_gpu_model() -> str:
    try:
        output = subprocess.check_output(
            ["wmic", "path", "win32_VideoController", "get", "Name"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        lines: List[str] = [line.strip() for line in output.splitlines() if line.strip()]
        filtered = [line for line in lines if line.lower() != "name"]
        if filtered:
            return filtered[0]
    except Exception:
        pass
    return "Unknown GPU"


def _get_ram_gb() -> str:
    try:
        total_gb = psutil.virtual_memory().total / (1024 ** 3)
        return f"{round(total_gb)} ГБ"
    except Exception:
        return "Unknown RAM"


def _get_windows_version() -> str:
    version = platform.version()
    release = platform.release()
    return f"Windows {release} ({version})"


def _get_architecture() -> str:
    arch = platform.machine() or "Unknown"
    if arch.upper() == "AMD64":
        return "x64"
    return arch


def init_hardware_cache() -> None:
    HARDWARE_CACHE.update(
        {
            "cpu": _get_cpu_model(),
            "gpu": _get_gpu_model(),
            "ram": _get_ram_gb(),
            "windows": _get_windows_version(),
            "arch": _get_architecture(),
        }
    )


def build_hardware_text() -> str:
    cache = HARDWARE_CACHE or {}
    parts = [
        "🖥️ Железо ПК:",
        f"🧠 CPU: {cache.get('cpu', 'Unknown CPU')}",
        f"🎮 GPU: {cache.get('gpu', 'Unknown GPU')}",
        f"💾 RAM: {cache.get('ram', 'Unknown RAM')}",
        f"🪟 Windows: {cache.get('windows', 'Unknown Windows')}",
        f"🧩 Архитектура: {cache.get('arch', 'Unknown')}",
    ]
    return "\n".join(parts)
