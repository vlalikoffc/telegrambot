# Plugins

Plugins extend the Windows backend without touching Telegram APIs. Place `.py` files in the top-level `plugins/` folder.

## Folder structure

```
plugins/
  example_plugin.py
  README.md
```

## Minimal plugin

```python
from system.plugins import PluginBase

class ExamplePlugin(PluginBase):
    name = "example"

    def on_snapshot(self, snapshot, ctx) -> None:
        snapshot.setdefault("plugins", {}).setdefault(self.name, {})["enabled"] = True

    def on_render(self, render_ctx, ctx) -> None:
        render_ctx.add_line("🔌 Example plugin active")
```

## Hooks

- `on_load(ctx)` – called once after loading.
- `on_snapshot(snapshot, ctx)` – mutate snapshot under `snapshot["plugins"][<name>]`.
- `on_render(render_ctx, ctx)` – append lines to the status output.
- `on_tick(ctx)` – optional async hook on a slow interval.
- `on_shutdown(ctx)` – called on shutdown.

## Rules

- Do not import or call Telegram APIs.
- Avoid blocking the event loop.
- Use `ctx.request_update()` to signal desired updates (core decides).

## Debugging

Plugin errors are isolated; failing plugins are disabled for the session.
