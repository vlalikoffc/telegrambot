"""
Status override example.

This plugin полностью заменяет статус через ctx.status.clear().
"""

from system.plugins import PluginBase


class StatusOverridePlugin(PluginBase):
    name = "status_override"
    version = "1.0.0"
    description = "Полностью заменяет текст статуса"

    def on_render(self, render_ctx, ctx) -> None:
        # Полная замена статуса. Остальные строки от core будут удалены.
        ctx.status.clear()
        ctx.status.add_line("📌 Кастомный статус от плагина")
        ctx.status.add_line("🔧 Всё под контролем")
        ctx.status.add_line(f"👀 Зрителей: {ctx.safe_state.get('viewer_count', 0)}")
