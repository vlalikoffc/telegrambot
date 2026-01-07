"""
Persistent storage example.

Сохраняет счётчик рендеров в ctx.storage (JSON).
"""

from system.plugins import PluginBase


class PersistentStoragePlugin(PluginBase):
    name = "persistent_storage"
    version = "1.0.0"
    description = "Хранит счётчик в storage.json"

    def on_render(self, render_ctx, ctx) -> None:
        # storage автоматически сохраняется в plugins/<name>/storage.json
        count = int(ctx.storage.get("render_count", 0)) + 1
        ctx.storage.set("render_count", count)
        ctx.status.add_line(f"💾 Рендеров плагина: {count}")
