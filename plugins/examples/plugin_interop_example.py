"""
Plugin interop example.

Показывает, как читать метаданные других плагинов (read-only).
"""

import re

from system.plugins import PluginBase


class PluginInteropExample(PluginBase):
    name = "plugin_interop"
    version = "1.0.0"
    description = "Считывает имена других плагинов из /plugins"

    def on_render(self, render_ctx, ctx) -> None:
        # Разрешено читать только файлы в plugins:/ (read-only).
        entries = ctx.fs.listdir("plugins:/")
        plugin_files = [name for name in entries if name.endswith(".py")]

        names = []
        for filename in plugin_files:
            try:
                content = ctx.fs.read_text(f"plugins:/{filename}")
            except Exception:
                continue
            match = re.search(r'\\bname\\s*=\\s*["\\\']([^"\\\']+)["\\\']', content)
            if match:
                names.append(match.group(1))

        if names:
            ctx.status.add_line("")
            ctx.status.add_line("🔗 Обнаружены плагины:")
            for name in sorted(set(names)):
                ctx.status.add_line(f"• {name}")
