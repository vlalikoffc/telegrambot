from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class DefaultStatusActiveApp:
    key: str
    name: str
    tagline: str
    uptime_seconds: Optional[float]
    minecraft_server: Optional[str]
    minecraft_client: Optional[str]


@dataclass(frozen=True)
class DefaultStatusPresence:
    state: str
    idle_seconds: Optional[float]
    duration_seconds: float


@dataclass(frozen=True)
class DefaultStatusFavorite:
    name: str
    running: bool
    active: bool


@dataclass(frozen=True)
class DefaultStatus:
    uptime_seconds: float
    local_time: str
    active_app: DefaultStatusActiveApp
    process_count: Optional[int]
    presence: DefaultStatusPresence
    favorites: Tuple[DefaultStatusFavorite, ...]
    work_languages: Tuple[str, ...]
    footer_text: str
    viewer_count: int
    update_interval_seconds: float


@dataclass
class RenderContext:
    lines: List[str] = field(default_factory=list)
    default_status: Optional[DefaultStatus] = None

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
