import asyncio
import importlib.util
import logging
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, List, Optional, Type

from .plugin_base import PluginBase
from .constants import CORE_PLUGIN_API_VERSION
from .filesystem import PluginFilesystem, PluginSandbox
from .plugin_context import PluginContext, PluginStorage
from .plugin_errors import PluginSecurityError
from .render_context import RenderContext
from .status_context import StatusContext


class PluginManager:
    def __init__(
        self,
        *,
        base_dir: Path,
        config: Dict[str, Any],
        platform: str,
        safe_state_provider: Callable[[], Dict[str, Any]],
    ) -> None:
        self._base_dir = base_dir
        self._config = config
        self._platform = platform
        self._safe_state_provider = safe_state_provider
        self._plugins: List[PluginBase] = []
        self._disabled: set[str] = set()
        self._failures: Dict[str, int] = {}
        self._update_requested = False
        self.logger = logging.getLogger("plugins")

    def request_update(self) -> None:
        self._update_requested = True

    def consume_update_request(self) -> bool:
        requested = self._update_requested
        self._update_requested = False
        return requested

    def _build_context(self, plugin: PluginBase, status: StatusContext) -> PluginContext:
        fs = PluginFilesystem(self._base_dir, plugin.name, self.logger)
        plugin_dir = fs.plugin_dir
        plugin_dir.mkdir(parents=True, exist_ok=True)
        storage = PluginStorage(plugin_dir / "storage.json")
        return PluginContext(
            logger=logging.getLogger(f"plugin.{plugin.name}"),
            config=self._config,
            safe_state=self._safe_state_provider(),
            storage=storage,
            fs=fs,
            status=status,
            platform=self._platform,
            request_update=self.request_update,
        )

    def _disable_plugin(self, plugin: PluginBase, reason: str) -> None:
        self._disabled.add(plugin.name)
        self.logger.warning("Plugin %s disabled: %s", plugin.name, reason)

    def _handle_failure(self, plugin: PluginBase, hook: str, exc: Exception) -> None:
        count = self._failures.get(plugin.name, 0) + 1
        self._failures[plugin.name] = count
        if isinstance(exc, PluginSecurityError):
            self.logger.error(
                "SECURITY VIOLATION: plugin=%s hook=%s path=%s operation=%s",
                plugin.name,
                hook,
                exc.path,
                exc.operation,
            )
            self._disable_plugin(plugin, "security violation")
            return
        self.logger.exception("Plugin %s failed in %s: %s", plugin.name, hook, exc)
        if count >= 3:
            self._disable_plugin(plugin, f"repeated failures in {hook}")

    def _iter_plugins(self) -> List[PluginBase]:
        return [plugin for plugin in self._plugins if plugin.name not in self._disabled]

    def load_plugins(self) -> None:
        plugin_dir = self._base_dir / "plugins"
        if not plugin_dir.exists():
            self.logger.info("Plugins folder not found, skipping")
            return
        for plugin_path in plugin_dir.glob("*.py"):
            if plugin_path.name.startswith("_"):
                continue
            module = self._load_module(plugin_path)
            if not module:
                continue
            api_version = getattr(module, "PLUGIN_API_VERSION", None)
            if api_version is None:
                self.logger.error(
                    "Plugin %s missing PLUGIN_API_VERSION (expected %s)",
                    plugin_path.name,
                    CORE_PLUGIN_API_VERSION,
                )
                continue
            if api_version != CORE_PLUGIN_API_VERSION:
                self.logger.error(
                    "Plugin %s incompatible PLUGIN_API_VERSION=%s (expected %s)",
                    plugin_path.name,
                    api_version,
                    CORE_PLUGIN_API_VERSION,
                )
                continue
            plugin_classes = self._discover_plugins(module)
            for plugin_cls in plugin_classes:
                plugin_name = getattr(plugin_cls, "name", None) or plugin_cls.__name__
                try:
                    sandbox = PluginSandbox(
                        PluginFilesystem(self._base_dir, plugin_name, self.logger),
                        self.logger,
                    )
                    with sandbox:
                        plugin = plugin_cls()
                except PluginSecurityError as exc:
                    self.logger.error(
                        "SECURITY VIOLATION: plugin=%s hook=init path=%s operation=%s",
                        plugin_name,
                        exc.path,
                        exc.operation,
                    )
                    self._disabled.add(plugin_name)
                    continue
                except Exception as exc:
                    self.logger.exception("Failed to instantiate plugin %s: %s", plugin_cls, exc)
                    continue
                if not plugin.name:
                    plugin.name = plugin_cls.__name__
                self._plugins.append(plugin)
        for plugin in self._plugins:
            self._call_hook(plugin, "on_load")

    def _load_module(self, path: Path) -> Optional[ModuleType]:
        sandbox = PluginSandbox(
            PluginFilesystem(self._base_dir, path.stem, self.logger),
            self.logger,
        )
        try:
            with sandbox:
                spec = importlib.util.spec_from_file_location(path.stem, path)
                if not spec or not spec.loader:
                    return None
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
        except PluginSecurityError as exc:
            self.logger.error(
                "SECURITY VIOLATION: plugin=%s hook=load_module path=%s operation=%s",
                path.stem,
                exc.path,
                exc.operation,
            )
            self._disabled.add(path.stem)
            return None
        except Exception as exc:
            self.logger.exception("Failed to load plugin module %s: %s", path.name, exc)
            return None

    def _discover_plugins(self, module: ModuleType) -> List[Type[PluginBase]]:
        plugins: List[Type[PluginBase]] = []
        for obj in module.__dict__.values():
            if isinstance(obj, type) and issubclass(obj, PluginBase) and obj is not PluginBase:
                plugins.append(obj)
        return plugins

    def _call_hook(self, plugin: PluginBase, hook: str, *args, status: Optional[StatusContext] = None) -> None:
        if plugin.name in self._disabled:
            return
        status_ctx = status or StatusContext(mode="status", _render=None)
        ctx = self._build_context(plugin, status_ctx)
        sandbox = PluginSandbox(ctx.fs, self.logger)
        try:
            with sandbox:
                handler = getattr(plugin, hook)
                handler(*args, ctx)
        except Exception as exc:
            self._handle_failure(plugin, hook, exc)

    def on_snapshot(self, snapshot: Dict[str, Any]) -> None:
        for plugin in self._iter_plugins():
            snapshot.setdefault("plugins", {}).setdefault(plugin.name, {})
            self._call_hook(plugin, "on_snapshot", snapshot, status=StatusContext(mode="status", _render=None))

    def on_render(self, render_ctx: RenderContext, mode: str = "status") -> None:
        for plugin in self._iter_plugins():
            status_ctx = StatusContext(mode=mode, _render=render_ctx)
            self._call_hook(plugin, "on_render", render_ctx, status=status_ctx)

    async def on_tick(self) -> None:
        for plugin in self._iter_plugins():
            ctx = self._build_context(plugin, StatusContext(mode="status", _render=None))
            sandbox = PluginSandbox(ctx.fs, self.logger)
            try:
                with sandbox:
                    await plugin.on_tick(ctx)
            except Exception as exc:
                self._handle_failure(plugin, "on_tick", exc)

    async def tick_loop(self, interval: float = 10.0) -> None:
        while True:
            try:
                await self.on_tick()
            except Exception as exc:
                self.logger.exception("Plugin tick loop error: %s", exc)
            await asyncio.sleep(interval)

    def on_shutdown(self) -> None:
        for plugin in self._iter_plugins():
            self._call_hook(plugin, "on_shutdown")
