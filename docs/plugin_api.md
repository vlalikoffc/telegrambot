# Plugin API

## Версионирование API

Core-версия API объявляется как `CORE_PLUGIN_API_VERSION`. Каждый плагин обязан указать `PLUGIN_API_VERSION` на уровне модуля.

- Если `PLUGIN_API_VERSION` отсутствует → плагин не загружается.
- Если `PLUGIN_API_VERSION` не совпадает с `CORE_PLUGIN_API_VERSION` → плагин не загружается.

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
- `ctx.fs` – controlled filesystem API (read/write only within allowed roots)
- `ctx.status` – status editing API (use in on_render)
- `ctx.platform` – "windows"
- `ctx.clock` – time helpers
- `ctx.request_update()` – signals that a refresh would be useful

## RenderContext

- `render_ctx.lines` – current list of lines
- `render_ctx.add_line(text)` – append line
- `render_ctx.add_section(title, lines)` – append titled section
- `render_ctx.extend(lines)` – append multiple lines
- `render_ctx.default_status` – read-only default status snapshot (structured data)

`default_status` содержит стабильные, безопасные поля:

- `uptime_seconds`
- `local_time`
- `active_app` (`key`, `name`, `tagline`, `uptime_seconds`, `minecraft_server`, `minecraft_client`)
- `process_count`
- `presence` (`state`, `idle_seconds`, `duration_seconds`)
- `favorites` (список: `name`, `running`, `active`)
- `work_languages`
- `footer_text`
- `viewer_count`
- `update_interval_seconds`

## StatusContext

- `ctx.status.clear()` – clear entire status
- `ctx.status.add_line(text)` – add line
- `ctx.status.append(text)` – alias for add_line
- `ctx.status.replace_section(title, lines)` – replace or add section
- `ctx.status.mode` – current render mode (`status`, reserved: `hardware`, `stats`, `more_info`)

## Storage

`ctx.storage` stores JSON data in `plugins/<plugin_name>/storage.json` and is isolated per plugin.

## Filesystem (ctx.fs)

- `ctx.fs.open(path, mode="r")`
- `ctx.fs.read_text(path)`
- `ctx.fs.write_text(path, data)`
- `ctx.fs.listdir(path="self:/")`
- `ctx.fs.exists(path)`

## Security

Attempting to read `.env` or access other plugin directories triggers a security violation and disables the plugin.
