import logging
import platform
import subprocess
from typing import Dict

import psutil

HARDWARE_CACHE: Dict[str, str] = {}
HARDWARE_TEXT = ""
_HARDWARE_INITIALIZED = False


def _get_cpu_model() -> str:
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if "model name" in line:
                    return line.split(":", 1)[1].strip()
    except Exception:
        logging.debug("CPU detection via /proc/cpuinfo failed", exc_info=True)
    cpu_name = platform.processor()
    return cpu_name or "Unknown CPU"


def _get_gpu_model() -> str:
    try:
        output = subprocess.check_output(
            ["bash", "-lc", "lspci | grep -i 'vga\|3d' | head -n1"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if output:
            parts = output.split(":")
            return parts[-1].strip() if ":" in output else output
    except Exception:
        logging.debug("GPU detection via lspci failed", exc_info=True)
    return "Unknown GPU"


def _get_ram_gb() -> str:
    try:
        total_gb = psutil.virtual_memory().total / (1024 ** 3)
        return f"{round(total_gb)} ГБ"
    except Exception:
        return "Unknown RAM"


def _get_linux_version() -> str:
    try:
        pretty = _read_os_release()
        if pretty:
            return pretty
    except Exception:
        logging.debug("/etc/os-release parse failed", exc_info=True)
    return f"Linux {platform.release()}"


def _read_os_release() -> str:
    path = "/etc/os-release"
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            data = fh.read().splitlines()
        items = dict(line.split("=", 1) for line in data if "=" in line)
        pretty = items.get("PRETTY_NAME")
        if pretty:
            return pretty.strip('"')
    except Exception:
        return ""
    return ""


def _get_architecture() -> str:
    arch = (platform.machine() or "Unknown").upper()
    if arch == "AMD64":
        return "x64"
    return arch.lower() if arch else "unknown"


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
            "windows": _get_linux_version(),
            "arch": _get_architecture(),
        }
    )
    HARDWARE_TEXT = "\n".join(
        [
            "🖥️ Железо ПК:",
            f"🧠 CPU: {HARDWARE_CACHE.get('cpu', 'Unknown CPU')}",
            f"🎮 GPU: {HARDWARE_CACHE.get('gpu', 'Unknown GPU')}",
            f"💾 RAM: {HARDWARE_CACHE.get('ram', 'Unknown RAM')}",
            f"🪟 Windows: {HARDWARE_CACHE.get('windows', 'Unknown Linux')}",
            f"🧩 Архитектура: {HARDWARE_CACHE.get('arch', 'unknown')}",
        ]
    )
    _HARDWARE_INITIALIZED = True


def build_hardware_text() -> str:
    return HARDWARE_TEXT or "🖥️ Железо ПК:\n(данные недоступны)"
