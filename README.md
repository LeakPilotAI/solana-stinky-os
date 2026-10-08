# Genesis / Stinky OS

Solana speculative-asset intelligence. Evidence first. Fail closed.

Gate 1 is **$33k / 5m volume**, clamp **$200k**. That is an investigation trigger, not a buy.

---

## Windows operator box (`D:\Work\Project-Genesis`)

The Genesis shortcut calls `Start-Stinky-OS.cmd`, then `start_genesis.py`.
Ordinary desktop startup uses `--core-only` and recovers only missing services from the seven-service collection/V2 profile: event-log, API, Sentinel, collector, entities, frontend and maintenance. Healthy services
and dependency containers remain untouched. Stale, unverified, orphan or duplicate
process chains fail closed. Native ownership and HTTP 200 are required; PID files
alone cannot establish health. Concurrent shortcut launches are serialized.

```powershell
.\.venv\Scripts\python.exe .\start_genesis.py --skip-sync
```

Use `--full` (alias `--full-startup`) explicitly to also recover the separate
persistent paper-intake-producer and paper-runtime services. Core-only mode leaves
any existing paper services untouched; it does not start absent ones. These services
are not required by frozen Intelligence Execution V2. See the
[paper-service audit](docs/PAPER_SERVICE_STARTUP_AUDIT.md).

`--skip-sync` never bypasses safety. `--keep` is a compatibility alias for safe
recovery. `--sync` and `--restart` are rejected; use separately reviewed workflows
for code synchronization and explicit stops. Startup never installs dependencies,
applies migrations, deletes/recreates containers or volumes, trims Redis history
or changes Redis configuration. Missing schema/environment blocks recovery.
Only existing ownership-verified stopped Genesis dependency containers can start.
Docker Desktop and Atlas are never started/stopped by this workflow.

Services use the supported detached per-service runner and survive launcher exit.
Actual endpoints are verified before opening http://127.0.0.1:3000/operator.
Service logs are preserved. Stop Genesis remains a separate explicit stop action.
See [safe recovery details](docs/SAFE_DESKTOP_RECOVERY.md).

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

---

## Architecture

Event-sourced. Dual store. Fail closed. See `docs/adr/` and `docs/GENESIS.md`.

Genesis does not trade, size positions, or analyze stocks, ETFs, portfolios, or perpetuals.
