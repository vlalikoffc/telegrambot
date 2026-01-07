"""
Multi-section example.

Создаёт структурированную секцию в статусе.
"""

from system.plugins import PluginBase


class MultiSectionPlugin(PluginBase):
    name = "multi_section"
    version = "1.0.0"
    description = "Добавляет секцию с несколькими строками"

    def on_render(self, render_ctx, ctx) -> None:
        # replace_section найдёт заголовок и заменит строки под ним.
        lines = [
            "• Пункт A",
            "• Пункт B",
            "• Пункт C",
        ]
        ctx.status.replace_section("Секция плагина", lines)
