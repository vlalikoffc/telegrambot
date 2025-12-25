import platform
import subprocess
from typing import List

import psutil


def _get_cpu_model() -> str:
    return platform.processor() or "Unknown CPU"


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
        return f"{total_gb:.1f} ГБ"
    except Exception:
        return "Unknown RAM"


def _get_windows_version() -> str:
    version = platform.version()
    release = platform.release()
    return f"Windows {release} ({version})"


def _get_architecture() -> str:
    return platform.machine() or "Unknown"


def build_hardware_text() -> str:
    parts = [
        "🖥️ Железо ПК:",
        f"🧠 CPU: {_get_cpu_model()}",
        f"🎮 GPU: {_get_gpu_model()}",
        f"💾 RAM: {_get_ram_gb()}",
        f"🪟 Windows: {_get_windows_version()}",
        f"🧩 Архитектура: {_get_architecture()}",
    ]
    return "\n".join(parts)
