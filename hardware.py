import platform
import subprocess
from typing import Dict, List

import psutil

HARDWARE_CACHE: Dict[str, str] = {}
HARDWARE_TEXT: str = ""
_HARDWARE_INITIALIZED = False


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
    global _HARDWARE_INITIALIZED
    global HARDWARE_TEXT
    if _HARDWARE_INITIALIZED:
        return
    HARDWARE_CACHE.update(
        {
            "cpu": _get_cpu_model(),
            "gpu": _get_gpu_model(),
            "ram": _get_ram_gb(),
            "windows": _get_windows_version(),
            "arch": _get_architecture(),
        }
    )
    HARDWARE_TEXT = "\n".join(
        [
            "🖥️ Железо ПК:",
            f"🧠 CPU: {HARDWARE_CACHE.get('cpu', 'Unknown CPU')}",
            f"🎮 GPU: {HARDWARE_CACHE.get('gpu', 'Unknown GPU')}",
            f"💾 RAM: {HARDWARE_CACHE.get('ram', 'Unknown RAM')}",
            f"🪟 Windows: {HARDWARE_CACHE.get('windows', 'Unknown Windows')}",
            f"🧩 Архитектура: {HARDWARE_CACHE.get('arch', 'Unknown')}",
        ]
    )
    _HARDWARE_INITIALIZED = True


def build_hardware_text() -> str:
    return HARDWARE_TEXT or "🖥️ Железо ПК:\n(данные недоступны)"
