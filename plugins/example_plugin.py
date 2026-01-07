from system.plugins import PluginBase

PLUGIN_API_VERSION = "1.0"


class ExamplePlugin(PluginBase):
    name = "example"
    version = "1.0.0"
    description = "Adds an example status line"
    author = "vlalikoffc"

    def on_load(self, ctx) -> None:
        ctx.logger.info("Example plugin loaded")

    def on_snapshot(self, snapshot, ctx) -> None:
        data = snapshot.setdefault("plugins", {}).setdefault(self.name, {})
        data["last_seen"] = ctx.clock.now()

    def on_render(self, render_ctx, ctx) -> None:
        viewer_count = ctx.safe_state.get("viewer_count", 0)
        render_ctx.add_section("Плагины", [f"Пример плагина активен (👀 {viewer_count})"])

    async def on_tick(self, ctx) -> None:
        counter = int(ctx.storage.get("ticks", 0)) + 1
        ctx.storage.set("ticks", counter)
