import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

import psutil
import win32gui
import win32process

PROCESS_COUNT_REFRESH_SECONDS = 10


@dataclass
class ProcessCountCache:
    count: Optional[int] = None
    updated_at: float = 0.0


process_count_cache = ProcessCountCache()


def get_system_uptime_seconds() -> float:
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    return (datetime.now() - boot_time).total_seconds()


def get_active_process_info() -> Dict[str, Any]:
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return {"name": "Unknown", "pid": None, "create_time": None}
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid:
            return {"name": "Unknown", "pid": None, "create_time": None}
        proc = psutil.Process(pid)
        return {
            "name": proc.name(),
            "pid": pid,
            "create_time": proc.create_time(),
        }
    except Exception:
        return {"name": "Unknown", "pid": None, "create_time": None}


def get_process_uptime_seconds(create_time: Optional[float]) -> Optional[float]:
    if not create_time:
        return None
    return time.time() - create_time


def get_process_count() -> Optional[int]:
    now = time.time()
    if now - process_count_cache.updated_at >= PROCESS_COUNT_REFRESH_SECONDS:
        try:
            process_count_cache.count = len(psutil.pids())
        except Exception:
            process_count_cache.count = None
        process_count_cache.updated_at = now
    return process_count_cache.count
