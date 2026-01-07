from typing import Optional


class PluginBase:
    name: str = "unknown"
    version: str = "0.0.0"
    description: Optional[str] = None
    author: Optional[str] = None

    def on_load(self, ctx) -> None:
        return None

    def on_snapshot(self, snapshot: dict, ctx) -> None:
        return None

    def on_render(self, render_ctx, ctx) -> None:
        return None

    def on_shutdown(self, ctx) -> None:
        return None

    async def on_tick(self, ctx) -> None:
        return None
