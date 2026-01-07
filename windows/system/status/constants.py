from typing import Dict

FOOTER_TEXT = "вот чё я делаю, но не следите пж за мной 24/7(мой юз в тг @vlalikoffc)"
HIDDEN_STATUS_TEXT = "🙈 Статус сейчас скрыт\n\nНажмите кнопку ниже, чтобы посмотреть актуальный статус."

BROWSER_PROCESS_NAMES = {
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "chromium.exe",
    "supermium.exe",
    "brave.exe",
    "bravebrowser.exe",
    "opera.exe",
    "opera_gx.exe",
}

PROCESS_ALIASES: Dict[str, str] = {
    **{name: "browser" for name in BROWSER_PROCESS_NAMES},
    "code.exe": "vscode",
    "telegram.exe": "telegram",
    "cs2.exe": "cs2",
    "csgo.exe": "cs2",
    "steam.exe": "steam",
    "discord.exe": "discord",
    "spotify.exe": "spotify",
    "obs64.exe": "obs",
    "obs32.exe": "obs",
    "java.exe": "java",
    "javaw.exe": "java",
}

DISPLAY_NAMES = {
    "browser": "Браузер",
    "vscode": "VS Code",
    "telegram": "Telegram",
    "cs2": "Counter-Strike 2",
    "steam": "Steam",
    "discord": "Discord",
    "spotify": "Spotify",
    "obs": "OBS",
    "minecraft": "Minecraft",
    "unknown": "Unknown",
}

TAGLINES = {
    "browser": "сижу просто так в интернете",
    "vscode": "страдаю хернёй (программирую)",
    "telegram": "залип в телеге",
    "cs2": "бегу на B",
    "steam": "катаю через Steam",
    "discord": "залип в дискорде",
    "spotify": "наслушиваюсь треков",
    "obs": "что-то записываю",
    "minecraft": "копаюсь в кубах",
    "default": "живу жизнь",
}

PYTHON_PROCESS_NAMES = {"python.exe", "python3.exe"}
JS_PROCESS_NAMES = {"node.exe", "nodejs.exe", "npm.cmd", "yarn.cmd", "pnpm.cmd"}

FAVORITE_APPS = {
    "minecraft": {"process_names": {"java.exe", "javaw.exe"}, "display": "Minecraft"},
    "browser": {"process_names": set(BROWSER_PROCESS_NAMES), "display": "Браузер"},
    "telegram": {"process_names": {"telegram.exe"}, "display": "Telegram"},
    "discord": {"process_names": {"discord.exe"}, "display": "Discord"},
    "spotify": {"process_names": {"spotify.exe"}, "display": "Spotify"},
    "obs": {"process_names": {"obs64.exe", "obs32.exe"}, "display": "OBS"},
    "vscode": {"process_names": {"code.exe"}, "display": "VS Code"},
    "cs2": {"process_names": {"cs2.exe", "csgo.exe"}, "display": "Counter-Strike 2"},
    "steam": {"process_names": {"steam.exe"}, "display": "Steam"},
}

ACTIVE_THRESHOLD_SECONDS = 300
