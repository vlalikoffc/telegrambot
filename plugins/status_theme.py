import json
import os
from dataclasses import asdict
from datetime import timedelta

from system.plugins import PluginBase

PLUGIN_API_VERSION = "1.1"


class StatusThemePlugin(PluginBase):
    name = "status_theme"
    version = "1.1.0"
    description = "Configurable status template powered by core default status data"
    author = "vlalikoffc"

    _CONFIG_PATH = "self:/config.json"
    _BACKUP_PATH = "self:/base_backup.json"

    def on_load(self, ctx) -> None:
        created = False
        if not ctx.fs.exists(self._CONFIG_PATH):
            self._write_json(ctx, self._CONFIG_PATH, self._default_config())
            created = True
        if not ctx.fs.exists(self._BACKUP_PATH):
            self._write_json(
                ctx,
                self._BACKUP_PATH,
                {
                    "note": "This snapshot is filled on first render.",
                    "default_status": {},
                },
            )
        if created:
            ctx.logger.info("Status theme initialized")
        self._store_config_mtime(ctx)

    def on_render(self, render_ctx, ctx) -> None:
        default_status = getattr(render_ctx, "default_status", None)
        if default_status is None:
            return

        config = self._load_config(ctx)
        if not config.get("enabled", True):
            return

        self._write_default_snapshot(ctx, default_status)

        ctx.status.clear()
        values = self._format_values(default_status, ctx.safe_state, config)
        sections = config.get("sections", {})
        section_titles = config.get("section_titles", {})
        order = config.get("section_order") or self._default_section_order()
        for section_key in order:
            self._render_section(
                ctx,
                default_status,
                values,
                section_key,
                sections,
                section_titles,
                config,
            )

    def on_tick(self, ctx) -> None:
        config = self._load_config(ctx)
        if not config.get("reload_on_change", True):
            return
        if not ctx.fs.exists(self._CONFIG_PATH):
            return
        try:
            mtime = os.stat(self._CONFIG_PATH).st_mtime
        except OSError:
            return
        last_mtime = ctx.storage.get("config_mtime")
        if last_mtime != mtime:
            ctx.storage.set("config_mtime", mtime)
            ctx.request_update()

    def _render_section(
        self,
        ctx,
        default_status,
        values: dict,
        section_key: str,
        sections: dict,
        section_titles: dict,
        config: dict,
    ) -> None:
        if section_key == "header":
            header = config.get("header")
            self._emit_lines(ctx, header, values)
            return
        if section_key == "footer":
            footer = config.get("footer")
            self._emit_lines(ctx, footer, values)
            return
        if section_key == "custom_lines":
            self._emit_lines(ctx, config.get("custom_lines", []), values)
            return

        if section_key not in sections:
            return
        section = sections.get(section_key)
        if not section:
            return

        if section_key == "offline" and default_status.active_app.key != "unknown":
            return
        if section_key in {"active_app", "minecraft"} and default_status.active_app.key == "unknown":
            return
        if section_key == "minecraft" and not self._has_minecraft(default_status):
            return

        title = section_titles.get(section_key)
        if title:
            ctx.status.add_line(self._safe_format(title, values))

        if section_key == "favorites":
            favorites_text = self._favorites_block(default_status, config)
            if not favorites_text:
                return
            values = dict(values)
            values["favorites"] = favorites_text
            self._emit_lines(ctx, section, values)
            return

        self._emit_lines(ctx, section, values)

    def _default_config(self) -> dict:
        return {
            "enabled": True,
            "header": "🖥️ PC STATUS",
            "footer": "👀 Viewers: {viewer_count}",
            "sections": {
                "active_app": "🎮 Active: {app_name}",
                "minecraft": [
                    "⛏ Minecraft {mc_version}",
                    "🌐 Server: {server}",
                ],
                "favorites": "⭐ Favorites:\n{favorites}",
                "offline": "💤 Nothing running",
            },
            "section_titles": {},
            "section_order": [
                "header",
                "active_app",
                "minecraft",
                "favorites",
                "offline",
                "custom_lines",
                "footer",
            ],
            "custom_lines": [
                "———",
                "⚙ Customized via Status Theme Plugin",
            ],
            "include_default_favorites": True,
            "custom_favorites": [],
            "favorite_templates": {
                "active": "▶️ {name}",
                "running": "🟢 {name}",
                "idle": "💤 {name}",
            },
            "reload_on_change": True,
        }

    @staticmethod
    def _default_section_order() -> list[str]:
        return [
            "header",
            "active_app",
            "minecraft",
            "favorites",
            "offline",
            "custom_lines",
            "footer",
        ]

    def _load_config(self, ctx) -> dict:
        if not ctx.fs.exists(self._CONFIG_PATH):
            config = self._default_config()
            self._write_json(ctx, self._CONFIG_PATH, config)
            ctx.logger.info("Status theme initialized")
            return config
        try:
            raw = ctx.fs.read_text(self._CONFIG_PATH)
            return json.loads(raw)
        except (OSError, json.JSONDecodeError):
            config = self._default_config()
            self._write_json(ctx, self._CONFIG_PATH, config)
            return config

    def _write_default_snapshot(self, ctx, default_status) -> None:
        snapshot = asdict(default_status)
        self._write_json(ctx, self._BACKUP_PATH, snapshot)

    def _write_json(self, ctx, path: str, payload: dict) -> None:
        ctx.fs.write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))

    def _emit_lines(self, ctx, template, values: dict) -> None:
        if not template:
            return
        if isinstance(template, list):
            for line in template:
                ctx.status.add_line(self._safe_format(line, values))
            return
        for line in str(template).splitlines():
            ctx.status.add_line(self._safe_format(line, values))

    def _favorites_block(self, default_status, config: dict) -> str:
        templates = config.get("favorite_templates", {})
        include_default = config.get("include_default_favorites", True)
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
        for custom in config.get("custom_favorites", []):
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
        lines = []
        for favorite in favorites:
            if favorite.get("active"):
                template = templates.get("active", "{name}")
            elif favorite.get("running"):
                template = templates.get("running", "{name}")
            else:
                template = templates.get("idle", "{name}")
            lines.append(self._safe_format(template, {"name": favorite["name"]}))
        return "\n".join(lines)

    def _format_values(self, default_status, safe_state: dict, config: dict) -> dict:
        uptime_seconds = default_status.uptime_seconds
        app_uptime_seconds = default_status.active_app.uptime_seconds
        presence_duration = default_status.presence.duration_seconds
        viewer_count = safe_state.get("viewer_count", 0)
        return {
            "uptime_seconds": self._format_number(uptime_seconds),
            "uptime_hms": self._format_duration(uptime_seconds),
            "local_time": default_status.local_time,
            "app_name": default_status.active_app.name,
            "app_key": default_status.active_app.key,
            "app_tagline": default_status.active_app.tagline,
            "app_uptime_seconds": self._format_number(app_uptime_seconds),
            "app_uptime_hms": self._format_duration(app_uptime_seconds),
            "mc_version": default_status.active_app.minecraft_client or "",
            "server": default_status.active_app.minecraft_server or "",
            "process_count": self._format_number(default_status.process_count),
            "presence_state": default_status.presence.state,
            "presence_idle_seconds": self._format_number(default_status.presence.idle_seconds),
            "presence_duration_seconds": self._format_number(presence_duration),
            "presence_duration_human": self._format_presence_duration(presence_duration),
            "footer_text": default_status.footer_text,
            "viewer_count": str(viewer_count),
            "update_interval": self._format_number(default_status.update_interval_seconds),
            "favorites": "",
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
            return "just now"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} min"
        hours = minutes // 60
        remaining_minutes = minutes % 60
        if remaining_minutes:
            return f"{hours} h {remaining_minutes} min"
        return f"{hours} h"

    @staticmethod
    def _safe_format(template: str, values: dict) -> str:
        class SafeDict(dict):
            def __missing__(self, key):
                return "{" + key + "}"

        return str(template).format_map(SafeDict(values))

    @staticmethod
    def _has_minecraft(default_status) -> bool:
        return bool(
            default_status.active_app.minecraft_client
            or default_status.active_app.minecraft_server
            or default_status.active_app.key == "minecraft"
        )

    @staticmethod
    def _store_config_mtime(ctx) -> None:
        if not ctx.fs.exists("self:/config.json"):
            return
        try:
            ctx.storage.set("config_mtime", os.stat("self:/config.json").st_mtime)
        except OSError:
            return
