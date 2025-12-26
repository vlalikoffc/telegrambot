# Telegram PC Status Bot (Windows + Linux)

Этот репозиторий содержит два backend-слоя с единым Telegram-интерфейсом:

- `windows/` — исходная Windows-реализация (pywin32, активное окно через Win32 API).
- `linux/` — порт для Linux (X11/Wayland best-effort, данные процессов и присутствия через psutil/xdotool/xprintidle при наличии).

Запуск идёт через корневой `main.py`, который автоматически выбирает нужную платформу по `platform.system()`, добавляет соответствующую папку в `PYTHONPATH` и передаёт выполнение в платформенный `main.py`. Telegram-интерфейс (кнопки, состояния, live-update, analytics) остаётся одинаковым на обеих платформах.

## Быстрый старт

1. Создайте виртуальное окружение и установите зависимости для вашей платформы:
   - **Windows:** `pip install -r windows/requirements.txt`
   - **Linux:** `pip install -r linux/requirements.txt`
2. Создайте `.env` в папке выбранной платформы рядом с её `main.py`:
   ```env
   BOT_TOKEN=123456:ABCDEF
   # DEFAULT_CHAT_ID по желанию
   ```
3. Запустите из корня репозитория:
   ```bash
   python main.py
   ```

## Документация по платформам

- Windows: см. `windows/README.md`
- Linux: см. `linux/README.md` (аналогичная структура и функционал, адаптированные под Linux)

## Лицензия

Проект распространяется под лицензией MIT. Сохраните атрибуцию исходного автора (vlalikoffc) при распространении или модификации.
