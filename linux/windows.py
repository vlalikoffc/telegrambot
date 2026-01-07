import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import psutil

PROCESS_COUNT_REFRESH_SECONDS = 10


@dataclass
class ProcessCountCache:
    count: Optional[int] = None
    updated_at: float = 0.0


process_count_cache = ProcessCountCache()


def _safe_check_output(cmd: List[str]) -> Optional[str]:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def _get_active_window_id() -> Optional[str]:
    # Best-effort: xdotool is common on X11; Wayland environments may return None.
    out = _safe_check_output(["xdotool", "getwindowfocus"])
    if out:
        return out.strip()
    return None


def _get_pid_for_window(window_id: str) -> Optional[int]:
    out = _safe_check_output(["xprop", "-id", window_id, "_NET_WM_PID"])
    if not out:
        return None
    if "= " in out:
        try:
            return int(out.split("= ")[-1].strip())
        except ValueError:
            return None
    return None


def _get_window_title(window_id: str) -> Optional[str]:
    out = _safe_check_output(["xdotool", "getwindowname", window_id])
    return out or None


def get_window_title_for_pid(pid: int) -> Optional[str]:
    # Walk through windows to find a matching PID (best-effort using xprop list)
    try:
        out = _safe_check_output(["wmctrl", "-lp"])
        if not out:
            return None
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            win_pid = int(parts[2])
            if win_pid != pid:
                continue
            win_id = parts[0]
            title = " ".join(parts[4:])
            return title or None
    except Exception:
        return None
    return None


def get_system_uptime_seconds() -> float:
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    return (datetime.now() - boot_time).total_seconds()


def get_local_time_string() -> str:
    return datetime.now().strftime("%H:%M:%S")


def get_local_date_string() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def format_local_hhmm(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%H:%M")


def get_last_input_idle_seconds() -> Optional[float]:
    # Try xprintidle (X11). Wayland fallback returns None.
    out = _safe_check_output(["xprintidle"])
    if out:
        try:
            return int(out) / 1000.0
        except ValueError:
            return None
    return None


def get_active_process_info() -> Dict[str, Any]:
    try:
        window_id = _get_active_window_id()
        if not window_id:
            return {"name": "Unknown", "pid": None, "create_time": None, "title": None}
        pid = _get_pid_for_window(window_id)
        proc = psutil.Process(pid) if pid else None
        title = _get_window_title(window_id)
        return {
            "name": proc.name() if proc else "Unknown",
            "pid": pid,
            "create_time": proc.create_time() if proc else None,
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
