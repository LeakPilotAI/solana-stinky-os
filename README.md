# Genesis / Stinky OS

Solana speculative-asset intelligence. Evidence first. Fail closed.

Gate 1 is **$150k / 5m volume**, clamp **$200k**. That is an investigation trigger, not a buy.

---

## Windows operator box (`D:\\Work\\Project-Genesis`)

Double-click **Genesis** on the desktop.

The shortcut runs `cmd.exe /d /k` with absolute paths at this folder. It does **not** depend on the current working directory, a prior terminal, or PowerShell execution policy.

Every **start**:

1. If API + operator UI are already healthy: print **ALREADY RUNNING** and reuse them (no duplicates)
2. Else start Genesis-owned infrastructure (Docker compose: Postgres 5433 / Redis 6380 / MinIO 9010)
3. Start backend, frontend, Sentinel in detached consoles so **closing the launcher window does not kill Genesis**
4. Health-check real endpoints, then open **http://127.0.0.1:3000/operator**

The launcher window **stays open** with the health table. Press a key to dismiss it. Services stay up.

Stop with the **Stop Genesis** desktop icon. Stop only kills Genesis-owned processes/containers (PID file, command line, compose project). It will not kill ATLAS.

To overwrite the folder from GitHub (`.env` kept), use **Refresh Genesis** — that is explicit, not part of a normal double-click.

Startup log: `logs\\startup.log` (secrets redacted).

| Need | Port | Owner |
|---|---|---|
| Operator UI | 3000 | Genesis |
| API | 8010 | Genesis |
| Event log | 8002 | Genesis |
| Postgres | 5433 | Genesis (`stinky-postgres`) |
| Redis | 6380 | Genesis (`stinky-redis`) |
| MinIO | 9010 / 9011 | Genesis |

Ports 8000 / 5432 / 6379 are left alone for ATLAS coexistence.

Discord with an empty token is UNKNOWN, not a crash of the rest of the box.

Recreate shortcuts:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\\install-desktop-shortcut.ps1
```

---

## Architecture

Event-sourced. Dual store. Fail closed. See `docs/adr/` and `docs/GENESIS.md`.

Genesis does not trade, size positions, or analyze stocks, ETFs, portfolios, or perpetuals.
