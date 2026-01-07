import json
from dataclasses import asdict
from datetime import timedelta

from system.plugins import PluginBase

PLUGIN_API_VERSION = "1.1"


class StatusThemePlugin(PluginBase):
    name = "status_theme"
    version = "1.0.0"
    description = "Configurable status layout based on default status data"
    author = "vlalikoffc"

    def on_render(self, render_ctx, ctx) -> None:
        default_status = getattr(render_ctx, "default_status", None)
        if default_status is None:
            return
        config = self._load_or_create_config(ctx, default_status)
        self._write_default_snapshot(ctx, default_status)

        ctx.status.clear()
        for section in config.get("sections", []):
            if not section.get("enabled", True):
                continue
            section_type = section.get("type", "lines")
            title = section.get("title")
            if title:
                ctx.status.add_line(title)
            if section_type == "favorites":
                self._render_favorites(ctx, default_status, section)
            elif section_type == "work_languages":
                self._render_work_languages(ctx, default_status, section)
            elif section_type == "presence":
                self._render_presence(ctx, default_status, section)
            else:
                self._render_lines(ctx, default_status, section)

    def _load_or_create_config(self, ctx, default_status) -> dict:
        if not ctx.fs.exists("self:/config.json"):
            config = self._default_config(default_status)
            self._write_json(ctx, "self:/config.json", config)
            return config
        try:
            raw = ctx.fs.read_text("self:/config.json")
            config = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            config = self._default_config(default_status)
            self._write_json(ctx, "self:/config.json", config)
        return config

    def _write_default_snapshot(self, ctx, default_status) -> None:
        snapshot = asdict(default_status)
        self._write_json(ctx, "self:/default_snapshot.json", snapshot)

    def _write_json(self, ctx, path: str, payload: dict) -> None:
        ctx.fs.write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))

    def _default_config(self, default_status) -> dict:
        header_lines = [
            "🖥️ Аптайм ПК: {uptime_hms}",
            "⌚ Время: {local_time}",
            "🪟 Активное приложение: {active_app_name}",
            "💬 Приписка: {active_app_tagline}",
        ]
        if default_status.active_app.uptime_seconds is not None:
            header_lines.append("⏱️ Аптайм приложения: {active_app_uptime_hms}")
        if default_status.active_app.minecraft_server:
            header_lines.append("🌐 Сервер: {minecraft_server}")
        if default_status.active_app.minecraft_client:
            header_lines.append("🧩 Client: {minecraft_client}")
        if default_status.process_count is not None:
            header_lines.append("🔢 Процессов: {process_count}")
        return {
            "version": 1,
            "sections": [
                {
                    "id": "header",
                    "type": "lines",
                    "title": None,
                    "enabled": True,
                    "lines": header_lines,
                },
                {
                    "id": "presence",
                    "type": "presence",
                    "title": None,
                    "enabled": True,
                    "templates": {
                        "active": "🟢 За компьютером: я здесь (последний ввод {presence_duration_human} назад)",
                        "afk": "💤 За компьютером: отошёл ({presence_duration_human})",
                        "unknown": "🟢 За компьютером: я здесь",
                    },
                },
                {
                    "id": "favorites",
                    "type": "favorites",
                    "title": "Избранные программы",
                    "enabled": True,
                    "include_default": True,
                    "custom_favorites": [],
                    "templates": {
                        "active": "▶️ {name}",
                        "running": "🟢 {name}",
                        "idle": "💤 {name}",
                    },
                },
                {
                    "id": "work_languages",
                    "type": "work_languages",
                    "title": "🧑‍💻 Сейчас работаю:",
                    "enabled": bool(default_status.work_languages),
                    "template": "• {language}",
                },
                {
                    "id": "footer",
                    "type": "lines",
                    "title": None,
                    "enabled": True,
                    "lines": [
                        "{footer_text}",
                        "{viewer_line}",
                        "⚡ Обновление каждые {update_interval} сек",
                    ],
                },
            ],
        }

    def _render_lines(self, ctx, default_status, section: dict) -> None:
        values = self._format_values(default_status)
        for line in section.get("lines", []):
            ctx.status.add_line(self._safe_format(line, values))

    def _render_presence(self, ctx, default_status, section: dict) -> None:
        values = self._format_values(default_status)
        templates = section.get("templates", {})
        state = default_status.presence.state
        template = templates.get(state)
        if not template:
            template = templates.get("unknown", "{presence_state}")
        ctx.status.add_line(self._safe_format(template, values))

    def _render_work_languages(self, ctx, default_status, section: dict) -> None:
        template = section.get("template", "{language}")
        for language in default_status.work_languages:
            ctx.status.add_line(self._safe_format(template, {"language": language}))

    def _render_favorites(self, ctx, default_status, section: dict) -> None:
        templates = section.get("templates", {})
        include_default = section.get("include_default", True)
        favorites = []
        if include_default:
            favorites.extend(
                {
                    "name": favorite.name,
                    "running": favorite.running,
                    "active": favorite.active,
                }
                for favorite in default_status.favorites
            )
        for custom in section.get("custom_favorites", []):
            name = custom.get("name")
            state = custom.get("state", "idle")
            if not name:
                continue
            favorites.append(
                {
                    "name": name,
                    "running": state in {"running", "active"},
                    "active": state == "active",
                }
            )
        for favorite in favorites:
            if favorite.get("active"):
                template = templates.get("active", "{name}")
            elif favorite.get("running"):
                template = templates.get("running", "{name}")
            else:
                template = templates.get("idle", "{name}")
            ctx.status.add_line(self._safe_format(template, {"name": favorite["name"]}))

    def _format_values(self, default_status) -> dict:
        uptime_seconds = default_status.uptime_seconds
        app_uptime_seconds = default_status.active_app.uptime_seconds
        presence_duration = default_status.presence.duration_seconds
        return {
            "uptime_seconds": self._format_number(uptime_seconds),
            "uptime_hms": self._format_duration(uptime_seconds),
            "local_time": default_status.local_time,
            "active_app_name": default_status.active_app.name,
            "active_app_key": default_status.active_app.key,
            "active_app_tagline": default_status.active_app.tagline,
            "active_app_uptime_seconds": self._format_number(app_uptime_seconds),
            "active_app_uptime_hms": self._format_duration(app_uptime_seconds),
            "minecraft_server": default_status.active_app.minecraft_server or "",
            "minecraft_client": default_status.active_app.minecraft_client or "",
            "process_count": self._format_number(default_status.process_count),
            "presence_state": default_status.presence.state,
            "presence_idle_seconds": self._format_number(default_status.presence.idle_seconds),
            "presence_duration_seconds": self._format_number(presence_duration),
            "presence_duration_human": self._format_presence_duration(presence_duration),
            "footer_text": default_status.footer_text,
            "viewer_count": str(default_status.viewer_count),
            "viewer_line": self._viewer_line(default_status.viewer_count),
            "update_interval": self._format_number(default_status.update_interval_seconds),
        }

    @staticmethod
    def _format_number(value) -> str:
        if value is None:
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    @staticmethod
    def _format_duration(seconds) -> str:
        if seconds is None:
            return ""
        return str(timedelta(seconds=max(0, int(seconds))))

    @staticmethod
    def _format_presence_duration(seconds) -> str:
        if seconds is None:
            return ""
        seconds = max(0, int(seconds))
        if seconds < 60:
            return "только что"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} мин"
        hours = minutes // 60
        remaining_minutes = minutes % 60
        if remaining_minutes:
            return f"{hours} ч {remaining_minutes} мин"
        return f"{hours} ч"

    @staticmethod
    def _viewer_line(viewer_count: int) -> str:
        if viewer_count > 0:
            return f"👀 Сейчас наблюдают за статусом: {viewer_count}"
        return "😴 Сейчас никто не смотрит"

    @staticmethod
    def _safe_format(template: str, values: dict) -> str:
        class SafeDict(dict):
            def __missing__(self, key):
                return "{" + key + "}"

        return template.format_map(SafeDict(values))
