from dataclasses import dataclass, field
from typing import Iterable, List


@dataclass
class RenderContext:
    lines: List[str] = field(default_factory=list)

    def add_line(self, line: str) -> None:
        if line:
            self.lines.append(line)

    def add_section(self, title: str, lines: Iterable[str]) -> None:
        if title:
            self.lines.append("")
            self.lines.append(title)
        for line in lines:
            if line:
                self.lines.append(line)

    def extend(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.add_line(line)
