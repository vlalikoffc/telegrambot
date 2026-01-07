import asyncio
import ipaddress
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import psutil

from state import ensure_app_state
from status import resolve_app_key, resolve_tagline
from windows import (
    get_active_process_info,
    get_process_uptime_seconds,
    get_window_title_for_pid,
    list_running_processes,
)

MC_VERSION_PATTERN = re.compile(r"\b(\d+\.\d+(?:\.\d+)?[a-z]?)\b")
PENDING_SNAPSHOT_LIMIT = 20


def _normalize_version(version: str) -> str:
    return re.sub(r"[a-z]+$", "", version, flags=re.IGNORECASE)


def _is_valid_mc_version(version: str) -> bool:
    normalized = _normalize_version(version)
    if normalized.startswith("0."):
        return False
    parts = normalized.split(".")
    if len(parts) < 2:
        return False
    try:
        major = int(parts[0])
        minor = int(parts[1])
    except ValueError:
        return False
    if major == 1:
        return True
    if major == 26:
        return minor >= 1
    return major > 26


def _extract_mc_version(title: Optional[str]) -> Optional[str]:
    if not title:
        return None
    for match in MC_VERSION_PATTERN.finditer(title):
        candidate = match.group(1)
        if _is_valid_mc_version(candidate):
            return candidate
    return None


def _mask_ip(address: str) -> str:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return address
    if isinstance(ip, ipaddress.IPv4Address):
        parts = address.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.***.***"
    return address


def _minecraft_server_for_pid(pid: int) -> Optional[str]:
    try:
        proc = psutil.Process(pid)
        for conn in proc.connections(kind="inet"):
            if not conn.raddr:
                continue
            host = conn.raddr.ip if hasattr(conn.raddr, "ip") else conn.raddr[0]
            if not host:
                continue
            try:
                ip = ipaddress.ip_address(host)
                if ip.is_private or ip.is_loopback:
                    return "LAN"
            except ValueError:
                return host
            return _mask_ip(host)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None
    except Exception:
        return None
    return None


def _detect_minecraft_title(pid: Optional[int]) -> Optional[str]:
    if not pid:
        return None
    title = get_window_title_for_pid(pid)
    if title and "minecraft" in title.lower():
        return title
    return None


def _snapshot_signature(snapshot: Dict[str, Any]) -> Tuple[Any, ...]:
    return (
        snapshot.get("app_key"),
        snapshot.get("minecraft_version"),
        snapshot.get("minecraft_server"),
    )


def _detect_active_snapshot() -> Dict[str, Any]:
    process_info = get_active_process_info()
    process_name = process_info.get("name") or "Unknown"
    pid = process_info.get("pid")
    create_time = process_info.get("create_time")
    title = process_info.get("title")
    app_key = resolve_app_key(process_name)
    minecraft_title = None

    if process_name.lower() in {"java", "java.exe", "javaw", "javaw.exe"}:
        minecraft_title = _detect_minecraft_title(pid)
        if minecraft_title:
            app_key = "minecraft"

    if app_key == "browser":
        title = None

    minecraft_version = _extract_mc_version(minecraft_title) if app_key == "minecraft" else None
    minecraft_server = _minecraft_server_for_pid(pid) if app_key == "minecraft" and pid else None
    app_uptime_seconds = get_process_uptime_seconds(create_time)

    return {
        "timestamp": time.time(),
        "app_key": app_key,
        "process_name": process_name,
        "pid": pid,
        "create_time": create_time,
        "app_uptime_seconds": app_uptime_seconds,
        "title": title,
        "minecraft_version": minecraft_version,
        "minecraft_server": minecraft_server,
        "tagline": resolve_tagline(app_key),
    }


def _collect_running_apps(processes: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    running: Dict[str, Dict[str, Any]] = {}
    for proc_info in processes:
        name = proc_info.get("name") or ""
        app_key = resolve_app_key(name)
        pid = proc_info.get("pid")
        title = None
        if name.lower() in {"java", "java.exe", "javaw", "javaw.exe"}:
            minecraft_title = _detect_minecraft_title(pid)
            if minecraft_title:
                app_key = "minecraft"
                version = _extract_mc_version(minecraft_title)
                title = f"Minecraft {version}" if version else "Minecraft"

        if app_key == "unknown":
            continue
        if app_key == "browser":
            title = None

        current = running.setdefault(
            app_key,
            {
                "pids": set(),
                "title": title,
            },
        )
        current["pids"].add(pid)
        if title:
            current["title"] = title
    return running


def _update_app_activity(state: Dict[str, Any], snapshot: Dict[str, Any]) -> None:
    app_key = snapshot.get("app_key")
    if not app_key or app_key == "unknown":
        return
    title = snapshot.get("title")
    if app_key == "browser":
        title = None
    if app_key == "minecraft":
        version = snapshot.get("minecraft_version")
        title = f"Minecraft {version}" if version else "Minecraft"
    app_state = ensure_app_state(state, app_key)
    app_state["last_active_ts"] = time.time()
    if title:
        app_state["last_title"] = title


def init_tracker_state(bot_data: Dict[str, Any]) -> Dict[str, Any]:
    tracker = bot_data.setdefault(
        "tracker",
        {
            "last_snapshot": None,
            "pending_snapshots": [],
            "running_apps": {},
            "process_list": [],
        },
    )
    return tracker


def get_tracker_snapshot(tracker: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return tracker.get("last_snapshot")


def get_running_apps(tracker: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return tracker.get("running_apps") or {}


def get_process_list(tracker: Dict[str, Any]) -> List[Dict[str, Any]]:
    return tracker.get("process_list") or []


def get_snapshot_for_publish(tracker: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    pending = tracker.get("pending_snapshots") or []
    if pending:
        snapshot = pending.pop(0)
        tracker["pending_snapshots"] = pending
        return snapshot
    return tracker.get("last_snapshot")


def _collect_snapshot_payload() -> Dict[str, Any]:
    processes = list_running_processes()
    snapshot = _detect_active_snapshot()
    running_apps = _collect_running_apps(processes)
    return {
        "snapshot": snapshot,
        "process_list": processes,
        "running_apps": running_apps,
    }


def _update_pending_snapshots(tracker: Dict[str, Any], snapshot: Dict[str, Any]) -> None:
    last_snapshot = tracker.get("last_snapshot")
    if last_snapshot is None or _snapshot_signature(snapshot) != _snapshot_signature(last_snapshot):
        pending = tracker.get("pending_snapshots") or []
        pending.append(snapshot)
        if len(pending) > PENDING_SNAPSHOT_LIMIT:
            pending.pop(0)
        tracker["pending_snapshots"] = pending
    tracker["last_snapshot"] = snapshot


async def tracker_loop(app) -> None:
    logging.info("Internal tracker started")
    tracker = init_tracker_state(app.bot_data)
    while True:
        try:
            payload = await asyncio.to_thread(_collect_snapshot_payload)
            snapshot = payload["snapshot"]
            tracker["running_apps"] = payload["running_apps"]
            tracker["process_list"] = payload["process_list"]
            _update_pending_snapshots(tracker, snapshot)
            state = app.bot_data.get("state")
            if state:
                _update_app_activity(state, snapshot)
        except Exception as exc:
            logging.exception("Tracker loop error: %s", exc)
        await asyncio.sleep(1)
