import time
from dataclasses import dataclass
from typing import Optional

from config import BOT_START_TIME


PRESENCE_THRESHOLD_SECONDS = 300


@dataclass
class PresenceInfo:
    state: str
    since: float
    idle_seconds: Optional[float]


def _state_since_for_idle(idle_seconds: float, now: float) -> float:
    if idle_seconds < PRESENCE_THRESHOLD_SECONDS:
        return now - idle_seconds
    return now - (idle_seconds - PRESENCE_THRESHOLD_SECONDS)


class PresenceTracker:
    def __init__(self) -> None:
        self._state = PresenceInfo(state="active", since=BOT_START_TIME, idle_seconds=None)

    def observe(self, idle_seconds: Optional[float], now: Optional[float] = None) -> PresenceInfo:
        current_time = now or time.time()
        if idle_seconds is None:
            return PresenceInfo(state="unknown", since=self._state.since, idle_seconds=None)

        state = "active" if idle_seconds < PRESENCE_THRESHOLD_SECONDS else "afk"
        since = _state_since_for_idle(idle_seconds, current_time)
        self._state = PresenceInfo(state=state, since=since, idle_seconds=idle_seconds)
        return self._state


def presence_duration_seconds(info: PresenceInfo, now: Optional[float] = None) -> float:
    current_time = now or time.time()
    return max(0.0, current_time - info.since)


PRESENCE_TRACKER = PresenceTracker()

