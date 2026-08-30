# Genesis / Stinky OS

Solana speculative-asset intelligence. Evidence first. Fail closed.

Gate 1 is **$150k / 5m volume**, clamp **$200k**. That is an investigation trigger, not a buy.

---

## Windows operator box (`D:\Work\Project-Genesis`)

One-time refresh (preserves `.env`):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\APPLY-refresh.ps1
```

That overwrites the folder from GitHub, keeps Discord/RPC secrets, installs desktop shortcuts, and starts the OS.

After that, double-click **Genesis** on the desktop. Every launch:

1. Stops the previous instance
2. Pulls latest `main` (`.env` kept)
3. Ensures Python venv + npm + Docker
4. Applies SQL migrations (operator tables included)
5. Starts sentinel, API, event-log, collector, entities, Discord, web
6. Opens **http://127.0.0.1:3000/operator**

Stop with the **Stop Genesis** desktop icon.

| Need | Port |
|---|---|
| Operator UI | 3000 |
| API | 8010 |
| Event log | 8002 |
| Postgres | 5433 |
| Redis | 6380 |

Discord with an empty token is UNKNOWN, not a crash of the rest of the box.

---

## Architecture

Event-sourced. Dual store. Fail closed. See `docs/adr/` and `docs/GENESIS.md`.

Genesis does not trade, size positions, or analyze stocks, ETFs, portfolios, or perpetuals.
