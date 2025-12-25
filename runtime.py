import time

from config import BOT_START_TIME


def get_bot_uptime_seconds() -> float:
    return max(0.0, time.time() - BOT_START_TIME)
