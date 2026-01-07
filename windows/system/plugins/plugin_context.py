import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict

from .filesystem import PluginFilesystem
from .status_context import StatusContext


class PluginStorage:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._data = {}
            return
        try:
            self._data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._data = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            return


class Clock:
    @staticmethod
    def now() -> float:
        return time.time()

    @staticmethod
    def monotonic() -> float:
        return time.monotonic()


class PluginContext:
    def __init__(
        self,
        *,
        logger: logging.Logger,
        config: Dict[str, Any],
        safe_state: Dict[str, Any],
        storage: PluginStorage,
        fs: PluginFilesystem,
        status: StatusContext,
        platform: str,
        request_update: Callable[[], None],
    ) -> None:
        self.logger = logger
        self.config = config
        self.safe_state = safe_state
        self.storage = storage
        self.fs = fs
        self.status = status
        self.platform = platform
        self._request_update = request_update
        self.clock = Clock()

    def request_update(self) -> None:
        self._request_update()
