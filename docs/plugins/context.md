# PluginContext

`ctx` — это безопасный контекст плагина. Через него **разрешённые** действия.

## ctx.status (главное)

Интерфейс управления статусом. Используйте в `on_render()`.

```python
def on_render(self, render_ctx, ctx):
    ctx.status.add_line("✅ Добавленная строка")
```

## ctx.safe_state

Только чтение. Содержит безопасные сведения о рантайме, без секретов.

Пример:

```python
viewer_count = ctx.safe_state.get("viewer_count", 0)
```

## ctx.storage

Хранилище данных плагина (JSON).  
Файл хранится в `plugins/<plugin_name>/storage.json`.

```python
count = int(ctx.storage.get("count", 0)) + 1
ctx.storage.set("count", count)
```

## ctx.fs

Контролируемый файловый доступ. **Только через `ctx.fs` разрешены операции с файлами.**

```python
text = ctx.fs.read_text("self:/notes.txt")
ctx.fs.write_text("self:/notes.txt", text + "\\nновая строка")
```

Доступные префиксы:

- `self:/` — папка вашего плагина
- `runtime:/` — read‑only файлы Windows‑бекенда
- `plugins:/` — read‑only корень папки `plugins/`

Подробные правила — в `filesystem_rules.md`.

## ctx.request_update()

Сигнализирует, что статус стоит обновить.

```python
ctx.request_update()
```

## ctx.logger

Логер плагина. Пишите всё важное сюда.

```python
ctx.logger.info("Плагин работает")
```
