"""
Conditional status example.

Добавляет строки только при определённых условиях.
"""

from system.plugins import PluginBase


class ConditionalStatusPlugin(PluginBase):
    name = "conditional_status"
    version = "1.0.0"
    description = "Добавляет строки при выполнении условий"

    def on_render(self, render_ctx, ctx) -> None:
        # Безопасное условие: если кто-то смотрит статус — добавляем строку.
        if ctx.safe_state.get("viewer_count", 0) > 0:
            ctx.status.add_line("👀 Статус сейчас просматривают")
