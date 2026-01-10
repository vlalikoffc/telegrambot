# Plugins: permissions

Permissions protect the bot from risky actions. A plugin must request a
permission before performing a protected action. The user decides whether
to allow it.

## How permissions work

- The core owns a per-plugin permissions file.
- Plugins cannot read or modify this file.
- A plugin calls `ctx.request_permission(key, reason)`.
- The user is prompted in the console (yes/no/always).

## Available permissions

- `allow_status_override`: replace core status sections or clear status
- `allow_buttons`: render custom buttons
- `allow_view_override`: change the view state
- `allow_network`: outbound network access
- `allow_system`: access to blocked system modules and APIs

## When to request

Request only when you need the permission. Do not request everything at
startup. Users should see a clear reason for each request.
