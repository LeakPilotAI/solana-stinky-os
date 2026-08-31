# Genesis / Stinky OS

Solana speculative-asset intelligence. Evidence first. Fail closed.

Gate 1 is **$150k / 5m volume**, clamp **$200k**. That is an investigation trigger, not a buy.

---

## Windows operator box (`D:\Work\Project-Genesis`)

If the desktop icon still flashes or fails, paste this **in the VS Code terminal** at the project folder. It overwrites the tree from GitHub (`main`), keeps `.env`, and remakes `Genesis.lnk`.

```powershell
cd D:\Work\Project-Genesis
git remote set-url origin https://github.com/LeakPilotAI/solana-stinky-os.git
git fetch origin
git reset --hard origin/main
git checkout -f -B main origin/main
powershell -NoProfile -ExecutionPolicy Bypass -File .\APPLY-launcher.ps1
```

Then **close any leftover Genesis windows**, start **Docker Desktop**, and double-click **Genesis** or **Stinky OS** on the desktop (same launcher).

That APPLY step remakes `Genesis.lnk` as `cmd.exe /d /k`. The start chain is:

`Genesis.lnk` → `Start-Stinky-OS.cmd` → `.venv\Scripts\python.exe start_genesis.py`

It does **not** load `start-stinky.ps1`. Windows Defender AMSI was blocking that PowerShell file at parse time.

VS Code equivalent: **Terminal → Run Task… → Apply Genesis Launcher**.

If `APPLY-launcher.ps1` is missing after the reset, remake the icon only:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-desktop-shortcut.ps1
```

Start from VS Code without the desktop icon:

```powershell
.\.venv\Scripts\python.exe .\start_genesis.py --skip-sync
```

To pull **and start**:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\APPLY-refresh.ps1
```

The shortcut is:

- Target: `C:\Windows\System32\cmd.exe`
- Arguments: `/d /k "D:\Work\Project-Genesis\Start-Stinky-OS.cmd"`
- Working directory: `D:\Work\Project-Genesis`

Every **start**:

1. If API + operator UI are already healthy: print **ALREADY RUNNING** and reuse them (no duplicates)
2. Else start Genesis-owned infrastructure (Docker compose: Postgres 5433 / Redis 6380 / MinIO 9010)
3. Start backend, frontend, Sentinel in detached consoles so **closing the launcher window does not kill Genesis**
4. Health-check real endpoints, then open **http://127.0.0.1:3000/operator**

The launcher window **stays open** with the health table. Press a key to dismiss it. Services stay up.

Stop with the **Stop Genesis** desktop icon. Stop only kills Genesis-owned processes/containers. It will not kill ATLAS.

Startup log: `logs\startup.log` (secrets redacted). Apply log: `logs\launcher-apply.log`.

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
