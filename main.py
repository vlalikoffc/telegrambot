import importlib
import os
import platform
import sys
from pathlib import Path

PLATFORM_MAP = {
    "windows": "windows",
    "win32": "windows",
    "cygwin": "windows",
    "linux": "linux",
}


def _detect_platform_folder() -> Path:
    system_name = platform.system().lower()
    folder_name = PLATFORM_MAP.get(system_name, "windows")
    base = Path(__file__).parent / folder_name
    if not base.exists():
        raise RuntimeError(f"Platform folder not found: {base}")
    return base


def main() -> None:
    base = _detect_platform_folder()
    sys.path.insert(0, str(base))
    os.chdir(base)
    module = importlib.import_module("main")
    module.main()


if __name__ == "__main__":
    main()
