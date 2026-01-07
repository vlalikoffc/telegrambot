from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from .plugin_errors import PluginError
from .render_context import RenderContext


@dataclass
class StatusContext:
    mode: str
    _render: Optional[RenderContext]

    def _ensure_render(self) -> RenderContext:
        if self._render is None:
            raise PluginError("Status context is only available during on_render")
        return self._render

    def clear(self) -> None:
        render = self._ensure_render()
        render.lines.clear()

    def add_line(self, line: str) -> None:
        render = self._ensure_render()
        render.add_line(line)

    def append(self, line: str) -> None:
        self.add_line(line)

    def extend(self, lines: Iterable[str]) -> None:
        render = self._ensure_render()
        render.extend(lines)

    def replace_section(self, title: str, lines: Iterable[str]) -> None:
        render = self._ensure_render()
        if not title:
            return
        new_lines = list(lines)
        idx = None
        for i, entry in enumerate(render.lines):
            if entry == title:
                idx = i
                break
        if idx is None:
            render.add_section(title, new_lines)
            return
        end = idx + 1
        while end < len(render.lines) and render.lines[end].strip() != "":
            end += 1
        render.lines[idx + 1 : end] = [line for line in new_lines if line]
