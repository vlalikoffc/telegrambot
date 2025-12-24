import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import psutil
import win32api
import win32gui
import win32process

PROCESS_COUNT_REFRESH_SECONDS = 10


@dataclass
class ProcessCountCache:
    count: Optional[int] = None
    updated_at: float = 0.0


process_count_cache = ProcessCountCache()


def _enum_windows_for_pid(target_pid: int) -> List[int]:
    hwnds: List[int] = []

    def callback(hwnd: int, hwnds_list: List[int]) -> None:
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == target_pid and win32gui.IsWindowVisible(hwnd):
                hwnds_list.append(hwnd)
        except Exception:
            return

    win32gui.EnumWindows(callback, hwnds)
    return hwnds


def get_window_title_for_pid(pid: int) -> Optional[str]:
    for hwnd in _enum_windows_for_pid(pid):
        try:
            title = win32gui.GetWindowText(hwnd) or None
            if title:
                return title
        except Exception:
            continue
    return None


def get_system_uptime_seconds() -> float:
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    return (datetime.now() - boot_time).total_seconds()


def get_local_time_string() -> str:
    return datetime.now().strftime("%H:%M:%S")


def get_last_input_idle_seconds() -> Optional[float]:
    try:
        last_input = win32api.GetLastInputInfo()
        current_tick = win32api.GetTickCount()
        if last_input is None or current_tick is None:
            return None
        idle_ms = current_tick - last_input
        return idle_ms / 1000.0
    except Exception:
        return None


def get_active_process_info() -> Dict[str, Any]:
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return {"name": "Unknown", "pid": None, "create_time": None, "title": None}
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid:
            return {"name": "Unknown", "pid": None, "create_time": None, "title": None}
        proc = psutil.Process(pid)
        title = win32gui.GetWindowText(hwnd) or None
        return {
            "name": proc.name(),
            "pid": pid,
            "create_time": proc.create_time(),
            "title": title,
        }
    except Exception:
        return {"name": "Unknown", "pid": None, "create_time": None, "title": None}


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


def list_running_processes() -> List[Dict[str, Any]]:
    processes: List[Dict[str, Any]] = []
    for proc in psutil.process_iter(attrs=["pid", "name", "create_time"]):
        try:
            info = proc.info
            processes.append(
                {
                    "pid": info.get("pid"),
                    "name": info.get("name"),
                    "create_time": info.get("create_time"),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        except Exception:
            continue
    return processes
