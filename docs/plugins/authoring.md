# Plugins: authoring guide

This document focuses on writing clean, user-friendly plugins.

## Plugin metadata (name, author, repo)

The hardware + plugins view reads metadata from your plugin class.
Set these fields so users see a clean name, author, and repo link:

```python
from system.plugins import PluginBase

class MyPlugin(PluginBase):
    name = "Status Theme"
    version = "1.0.0"
    description = "Custom layout for the status message"
    author = "your-name"
    repo_url = "https://github.com/your/repo"
    api_version = "2.0.0"
```

Rules:
- `name` is what users see in the UI. Keep it human, no underscores.
- `author` is shown under the name.
- `repo_url` is shown as a clickable link; if empty, the UI says the
  developer did not provide a link.

## File layout

Keep plugin files small and readable. If you need helpers, create a
subfolder (for example `plugins/my_plugin/`) and import from there.

## Logging

Use `ctx.logger` for plugin logs. Avoid printing directly.
Log at INFO for normal events, WARNING for recoverable issues, ERROR for
failures that disable features.
