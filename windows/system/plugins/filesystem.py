from __future__ import annotations

import io
import logging
import os
import pathlib
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional
import re

from .plugin_errors import PluginSecurityError


def _has_env_segment(path: Path) -> bool:
    for segment in path.parts:
        if segment.startswith(".env"):
            return True
    return False


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


@dataclass(frozen=True)
class ResolvedPath:
    raw: Path
    resolved: Path


class PluginFilesystem:
    def __init__(self, base_dir: Path, plugin_name: str, logger: logging.Logger) -> None:
        self._base_dir = base_dir
        self._plugin_name = self._sanitize_plugin_name(plugin_name)
        self._windows_dir = base_dir / "windows"
        self._plugins_dir = base_dir / "plugins"
        self._plugin_dir = self._plugins_dir / self._plugin_name
        self._logger = logger
        self._raw_open = open
        self._raw_os_open = os.open

    @staticmethod
    def _sanitize_plugin_name(name: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
        cleaned = cleaned.replace("..", "_")
        cleaned = cleaned.strip("._-")
        return cleaned or "plugin"

    @property
    def plugin_dir(self) -> Path:
        return self._plugin_dir

    def _resolve_path(self, path: str | Path) -> ResolvedPath:
        raw = Path(path)
        if not raw.is_absolute():
            raw = self._plugin_dir / raw
        resolved = raw.expanduser().resolve()
        return ResolvedPath(raw=raw, resolved=resolved)

    def _resolve_virtual(self, path: str | Path) -> ResolvedPath:
        if isinstance(path, Path):
            return self._resolve_path(path)
        if path.startswith("self:/"):
            raw = self._plugin_dir / path[len("self:/") :]
            return ResolvedPath(raw=raw, resolved=raw.expanduser().resolve())
        if path.startswith("runtime:/"):
            raw = self._windows_dir / path[len("runtime:/") :]
            return ResolvedPath(raw=raw, resolved=raw.expanduser().resolve())
        if path.startswith("plugins:/"):
            raw = self._plugins_dir / path[len("plugins:/") :]
            return ResolvedPath(raw=raw, resolved=raw.expanduser().resolve())
        return self._resolve_path(path)

    def _validate(self, path: str | Path, *, operation: str, write: bool) -> Path:
        resolved = self._resolve_virtual(path)
        raw_path = resolved.raw
        real_path = resolved.resolved

        if _has_env_segment(raw_path) or _has_env_segment(real_path):
            raise PluginSecurityError(
                "Access to .env files is forbidden",
                path=str(raw_path),
                operation=operation,
            )

        if _is_within(real_path, self._plugin_dir):
            return real_path

        if _is_within(real_path, self._windows_dir):
            if write:
                raise PluginSecurityError(
                    "Write access to runtime files is forbidden",
                    path=str(raw_path),
                    operation=operation,
                )
            return real_path

        if _is_within(real_path, self._plugins_dir):
            if _is_within(real_path, self._plugin_dir):
                return real_path
            if real_path == self._plugins_dir or real_path.parent == self._plugins_dir:
                if write:
                    raise PluginSecurityError(
                        "Write access to /plugins is forbidden",
                        path=str(raw_path),
                        operation=operation,
                    )
                return real_path
            raise PluginSecurityError(
                "Access to other plugin directories is forbidden",
                path=str(raw_path),
                operation=operation,
            )

        raise PluginSecurityError(
            "Access outside sandbox roots is forbidden",
            path=str(raw_path),
            operation=operation,
        )

    def open(self, path: str | Path, mode: str = "r", *args, **kwargs):
        if isinstance(path, int):
            raise PluginSecurityError(
                "Opening file descriptors is forbidden",
                path=str(path),
                operation="open",
            )
        write = any(flag in mode for flag in ("w", "a", "x", "+"))
        real_path = self._validate(path, operation="open", write=write)
        if write:
            real_path.parent.mkdir(parents=True, exist_ok=True)
        return self._raw_open(real_path, mode, *args, **kwargs)

    def read_text(self, path: str | Path, encoding: str = "utf-8") -> str:
        real_path = self._validate(path, operation="read_text", write=False)
        return real_path.read_text(encoding=encoding)

    def write_text(self, path: str | Path, data: str, encoding: str = "utf-8") -> None:
        real_path = self._validate(path, operation="write_text", write=True)
        real_path.parent.mkdir(parents=True, exist_ok=True)
        real_path.write_text(data, encoding=encoding)

    def listdir(self, path: str | Path = "self:/") -> list[str]:
        real_path = self._validate(path, operation="listdir", write=False)
        return [entry.name for entry in real_path.iterdir()]

    def exists(self, path: str | Path) -> bool:
        real_path = self._validate(path, operation="exists", write=False)
        return real_path.exists()

    def os_open(self, path: str | Path, flags: int, mode: int = 0o777) -> int:
        write_flags = (
            os.O_WRONLY
            | os.O_RDWR
            | os.O_APPEND
            | os.O_CREAT
            | os.O_TRUNC
        )
        write = bool(flags & write_flags)
        real_path = self._validate(path, operation="os.open", write=write)
        if write:
            real_path.parent.mkdir(parents=True, exist_ok=True)
        return self._raw_os_open(real_path, flags, mode)

    def set_openers(self, *, open_func: Callable, os_open_func: Callable) -> None:
        self._raw_open = open_func
        self._raw_os_open = os_open_func


class PluginSandbox(AbstractContextManager["PluginSandbox"]):
    def __init__(self, fs: PluginFilesystem, logger: logging.Logger) -> None:
        self._fs = fs
        self._logger = logger
        self._original_open: Optional[Callable] = None
        self._original_io_open: Optional[Callable] = None
        self._original_os_open: Optional[Callable] = None
        self._original_os_listdir: Optional[Callable] = None
        self._original_os_scandir: Optional[Callable] = None
        self._original_os_stat: Optional[Callable] = None
        self._original_os_path_exists: Optional[Callable] = None
        self._original_os_path_isfile: Optional[Callable] = None
        self._original_os_path_isdir: Optional[Callable] = None
        self._original_path_open: Optional[Callable] = None

    def __enter__(self) -> "PluginSandbox":
        import builtins

        self._original_open = builtins.open
        self._fs.set_openers(open_func=self._original_open, os_open_func=os.open)
        builtins.open = self._fs.open

        self._original_io_open = io.open
        io.open = self._fs.open

        self._original_os_open = os.open
        os.open = self._fs.os_open

        self._original_os_listdir = os.listdir
        os.listdir = lambda path="." : self._fs.listdir(path)

        self._original_os_scandir = os.scandir
        os.scandir = lambda path=".": self._guard_scandir(path)

        self._original_os_stat = os.stat
        os.stat = lambda path, *args, **kwargs: self._guard_stat(path)

        self._original_os_path_exists = os.path.exists
        os.path.exists = lambda path: self._fs.exists(path)

        self._original_os_path_isfile = os.path.isfile
        os.path.isfile = lambda path: self._guard_isfile(path)

        self._original_os_path_isdir = os.path.isdir
        os.path.isdir = lambda path: self._guard_isdir(path)

        self._original_path_open = pathlib.Path.open
        pathlib.Path.open = lambda path_obj, *args, **kwargs: self._fs.open(path_obj, *args, **kwargs)
        return self

    def _guard_scandir(self, path: str | Path) -> Iterator[os.DirEntry]:
        real_path = self._fs._validate(path, operation="scandir", write=False)
        return self._original_os_scandir(real_path)  # type: ignore[arg-type]

    def _guard_stat(self, path: str | Path):
        real_path = self._fs._validate(path, operation="stat", write=False)
        return self._original_os_stat(real_path)

    def _guard_isfile(self, path: str | Path) -> bool:
        real_path = self._fs._validate(path, operation="isfile", write=False)
        if self._original_os_path_isfile is None:
            return Path(real_path).is_file()
        return self._original_os_path_isfile(real_path)

    def _guard_isdir(self, path: str | Path) -> bool:
        real_path = self._fs._validate(path, operation="isdir", write=False)
        if self._original_os_path_isdir is None:
            return Path(real_path).is_dir()
        return self._original_os_path_isdir(real_path)

    def __exit__(self, exc_type, exc, tb) -> None:
        import builtins

        if self._original_open is not None:
            builtins.open = self._original_open
        if self._original_io_open is not None:
            io.open = self._original_io_open
        if self._original_os_open is not None:
            os.open = self._original_os_open
        if self._original_os_listdir is not None:
            os.listdir = self._original_os_listdir
        if self._original_os_scandir is not None:
            os.scandir = self._original_os_scandir
        if self._original_os_stat is not None:
            os.stat = self._original_os_stat
        if self._original_os_path_exists is not None:
            os.path.exists = self._original_os_path_exists
        if self._original_os_path_isfile is not None:
            os.path.isfile = self._original_os_path_isfile
        if self._original_os_path_isdir is not None:
            os.path.isdir = self._original_os_path_isdir
        if self._original_path_open is not None:
            pathlib.Path.open = self._original_path_open
        return None
