import asyncio
import ipaddress
import logging
import re
import socket
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
CLIENT_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("Lunar Client", re.compile(r"Lunar\s+Client(?:\s+v?([0-9][\w.\-]+))?", re.IGNORECASE)),
    ("LabyMod", re.compile(r"LabyMod(?:\s+v?([0-9][\w.\-]+))?", re.IGNORECASE)),
    ("Feather", re.compile(r"Feather(?:\s+Client)?(?:\s+v?([0-9][\w.\-]+))?", re.IGNORECASE)),
    ("Badlion", re.compile(r"Badlion(?:\s+Client)?(?:\s+v?([0-9][\w.\-]+))?", re.IGNORECASE)),
    ("Fabric Loader", re.compile(r"Fabric(?:\s+Loader)?(?:\s+v?([0-9][\w.\-]+))?", re.IGNORECASE)),
    ("Forge", re.compile(r"Forge(?:\s+v?([0-9][\w.\-]+))?", re.IGNORECASE)),
)

MIN_MINECRAFT_SERVER_SECONDS = 5.0
MIN_MINECRAFT_SERVER_TICKS = 2
BLOCKED_PORTS = {443}
BLOCKED_IP_PREFIXES = {13, 18, 34}
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


def _is_blocked_ip(ip: ipaddress.IPv4Address) -> bool:
    return ip.is_private or ip.is_loopback or ip.packed[0] in BLOCKED_IP_PREFIXES


def _resolve_domain(host: str) -> Optional[str]:
    try:
        hostname, _, _ = socket.gethostbyaddr(host)
    except OSError:
        return None
    if hostname and hostname != host:
        return hostname
    return None


def _collect_java_connections(pid: int) -> List[tuple[str, int, bool]]:
    try:
        proc = psutil.Process(pid)
        if proc.name().lower() not in {"java.exe", "javaw.exe"}:
            return []
        results: List[tuple[str, int, bool]] = []
        for conn in proc.connections(kind="inet"):
            if not conn.raddr:
                continue
            host = conn.raddr.ip if hasattr(conn.raddr, "ip") else conn.raddr[0]
            port = conn.raddr.port if hasattr(conn.raddr, "port") else conn.raddr[1]
            if not host or port in BLOCKED_PORTS:
                continue
            try:
                ip = ipaddress.ip_address(host)
                if _is_blocked_ip(ip):
                    if ip.is_private or ip.is_loopback:
                        results.append(("LAN", port, True))
                    continue
                domain = _resolve_domain(host)
                if domain:
                    results.append((domain, port, True))
                else:
                    results.append((host, port, False))
            except ValueError:
                results.append((host, port, True))
        return results
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []
    except Exception:
        return []


def _detect_minecraft_title(pid: Optional[int]) -> Optional[str]:
    if not pid:
        return None
    title = get_window_title_for_pid(pid)
    if title and "minecraft" in title.lower():
        return title
    return None


def _detect_minecraft_client(
    title: Optional[str], minecraft_version: Optional[str]
) -> Optional[str]:
    if not title:
        return None
    for name, pattern in CLIENT_PATTERNS:
        match = pattern.search(title)
        if not match:
            continue
        version = match.group(1)
        if version and minecraft_version and version == minecraft_version:
            version = None
        if version and minecraft_version and version.startswith("1.") and name in {
            "Lunar Client",
            "LabyMod",
            "Feather",
            "Badlion",
        }:
            version = None
        if version:
            return f"{name} {version}"
        return name
    return None


def _select_persistent_server(
    tracker: Dict[str, Any], pid: Optional[int], now_ts: float
) -> Optional[str]:
    if not pid:
        return None
    candidates = tracker.setdefault("server_candidates", {})
    current_keys: set[tuple[str, int]] = set()
    for host, port, is_domain in _collect_java_connections(pid):
        key = (host, port)
        current_keys.add(key)
        entry = candidates.get(key)
        if not entry:
            candidates[key] = {
                "first_seen": now_ts,
                "last_seen": now_ts,
                "ticks": 1,
                "is_domain": is_domain,
            }
        else:
            entry["last_seen"] = now_ts
            entry["ticks"] = int(entry.get("ticks", 0)) + 1
            entry["is_domain"] = entry.get("is_domain") or is_domain

    stale_keys = [key for key in candidates if key not in current_keys]
    for key in stale_keys:
        candidates.pop(key, None)

    ordered = sorted(
        candidates.items(),
        key=lambda item: (not bool(item[1].get("is_domain")), item[0]),
    )
    for (host, port), entry in ordered:
        duration = now_ts - float(entry.get("first_seen", now_ts))
        ticks = int(entry.get("ticks", 0))
        if duration >= MIN_MINECRAFT_SERVER_SECONDS and ticks >= MIN_MINECRAFT_SERVER_TICKS:
            if host == "LAN":
                return "LAN"
            return f"{host}:{port}"
    return None


def _detect_active_snapshot() -> Dict[str, Any]:
    process_info = get_active_process_info()
    process_name = process_info.get("name") or "Unknown"
    pid = process_info.get("pid")
    create_time = process_info.get("create_time")
    title = process_info.get("title")
    app_key = resolve_app_key(process_name)
    minecraft_title = None

    if process_name.lower() in {"java.exe", "javaw.exe"}:
        minecraft_title = _detect_minecraft_title(pid)
        if minecraft_title:
            app_key = "minecraft"

    if app_key == "browser":
        title = None

    minecraft_version = _extract_mc_version(minecraft_title) if app_key == "minecraft" else None
    minecraft_client = (
        _detect_minecraft_client(minecraft_title, minecraft_version) if app_key == "minecraft" else None
    )
    minecraft_server = None
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
        "minecraft_client": minecraft_client,
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
        if name.lower() in {"java.exe", "javaw.exe"}:
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
            "running_apps": {},
            "process_list": [],
            "server_candidates": {},
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


def _update_latest_snapshot(tracker: Dict[str, Any], snapshot: Dict[str, Any]) -> None:
    tracker["last_snapshot"] = snapshot


async def tracker_loop(app) -> None:
    logging.info("Internal tracker started")
    tracker = init_tracker_state(app.bot_data)
    while True:
        try:
            payload = await asyncio.to_thread(_collect_snapshot_payload)
            snapshot = payload["snapshot"]
            now_ts = time.time()
            if snapshot.get("app_key") == "minecraft":
                server = _select_persistent_server(tracker, snapshot.get("pid"), now_ts)
                snapshot["minecraft_server"] = server
            tracker["running_apps"] = payload["running_apps"]
            tracker["process_list"] = payload["process_list"]
            _update_latest_snapshot(tracker, snapshot)
            state = app.bot_data.get("state")
            if state:
                _update_app_activity(state, snapshot)
        except Exception as exc:
            logging.exception("Tracker loop error: %s", exc)
        await asyncio.sleep(1)
