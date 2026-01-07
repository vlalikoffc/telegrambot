import re
from typing import Tuple

MC_VERSION_PATTERN = re.compile(r"\b(\d+\.\d+(?:\.\d+)?[a-z]?)\b")
CLIENT_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("Lunar Client", re.compile(r"Lunar\s+Client(?:\s+v?([0-9][\w.\-]+))?", re.IGNORECASE)),
    ("LabyMod", re.compile(r"LabyMod(?:\s+v?([0-9][\w.\-]+))?", re.IGNORECASE)),
    ("Feather", re.compile(r"Feather(?:\s+Client)?(?:\s+v?([0-9][\w.\-]+))?", re.IGNORECASE)),
    ("Badlion", re.compile(r"Badlion(?:\s+Client)?(?:\s+v?([0-9][\w.\-]+))?", re.IGNORECASE)),
    ("Fabric Loader", re.compile(r"Fabric(?:\s+Loader)?(?:\s+v?([0-9][\w.\-]+))?", re.IGNORECASE)),
    ("Forge", re.compile(r"Forge(?:\s+v?([0-9][\w.\-]+))?", re.IGNORECASE)),
)

MIN_MINECRAFT_SERVER_SECONDS = 5.0
MIN_MINECRAFT_SERVER_TICKS = 2
BLOCKED_PORTS = {443}
BLOCKED_IP_PREFIXES = {13, 18, 34}
