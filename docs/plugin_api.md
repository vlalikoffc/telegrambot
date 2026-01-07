# Plugin API

## PluginBase

```python
class PluginBase:
    name: str
    version: str
    description: str | None
    author: str | None

    def on_load(self, ctx): pass
    def on_snapshot(self, snapshot, ctx): pass
    def on_render(self, render_ctx, ctx): pass
    def on_shutdown(self, ctx): pass
    async def on_tick(self, ctx): pass
```

## PluginContext

- `ctx.logger` – plugin-scoped logger
- `ctx.config` – plugin config dict
- `ctx.safe_state` – read-only runtime info
- `ctx.storage` – per-plugin JSON storage
- `ctx.platform` – "windows"
- `ctx.clock` – time helpers
- `ctx.request_update()` – signals that a refresh would be useful

## RenderContext

- `render_ctx.lines` – current list of lines
- `render_ctx.add_line(text)` – append line
- `render_ctx.add_section(title, lines)` – append titled section
- `render_ctx.extend(lines)` – append multiple lines

## Storage

`ctx.storage` stores JSON data in `plugins/.storage/<plugin_name>.json` and is isolated per plugin.
