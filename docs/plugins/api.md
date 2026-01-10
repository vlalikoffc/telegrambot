# Plugins: core API

This file summarizes the core plugin API surface. It lists the fields and
calls that plugins can rely on in the current version.

## PluginBase fields

Set these class attributes on your plugin:

- `name` (required): display name shown to users
- `version` (required): plugin version string
- `description` (recommended): one-line summary
- `author` (recommended): developer name or handle
- `repo_url` (recommended): download or repository link
- `api_version` (required): "2.0.0"

## Lifecycle hooks

Implement any of these methods:

- `on_start(ctx)`: plugin loaded and ready
- `on_tick(ctx)`: called every live update tick
- `on_render(ctx)`: called before the status message is sent/edited
- `on_stop(ctx)`: bot shutdown

## UI hooks

- `get_status_keyboard(ctx) -> list | None`: return a custom keyboard
- `on_callback(ctx, data) -> bool`: handle button clicks
- `get_hidden_status_text(ctx) -> str | None`: override hidden-status text

## Core context helpers

Use these `ctx` calls:

- `ctx.request_permission(key, reason=...) -> bool`
- `ctx.has_permission(key) -> bool`
- `ctx.require_permission(key, reason=...)`
- `ctx.request_update()`: ask core to update status sooner

Status building is available through `ctx.status` during `on_render`.
See `status_api.md` for details.
