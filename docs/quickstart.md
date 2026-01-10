# Quick start

This guide gets the bot running with a minimal configuration.

## 1) Configure secrets

Create `.env` in the project root and set your bot token. Keep this file
private and never commit it.

## 2) Run the bot

```powershell
python main.py
```

## 3) Open the status view

Open a chat with the bot and press the status button. The bot pins a
single status message and edits it on each update tick.

## 4) Enable plugins

Drop a plugin file into `plugins/` and restart the bot. See
`docs/plugins/README.md` for full plugin documentation.
