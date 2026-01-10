# Plugins: sandbox

The sandbox limits what plugins can do. This reduces the risk of a plugin
causing system damage or leaking sensitive data.

## What is blocked by default

- Access to core config and secrets
- Network requests
- Arbitrary file system access
- Executing scripts or system commands
- Importing blocked system or network modules

## How to work within the sandbox

- Store data in your plugin folder
- Cache results to avoid frequent operations
- Request permissions only when needed
- Prefer `ctx.storage` for small state
