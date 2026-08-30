# Module: sentinel (v0.1.0)

**Status:** First working vertical slice  
**Date:** 2026-08-10  

## Purpose

Real-time Solana launch detection for Stinky OS.

First milestone loop:

```
pump.fun Create (logsSubscribe)
  → decode mint + deployer (+ name/symbol when present)
  → fetch lightweight creator wallet history
  → publish TOKEN_LAUNCH event (Redis + Event Log HTTP)
```

## Run

```bash
# From repo root, venv active, infra up
pip install -e "./services/sentinel[dev]"

# Optional: set a better RPC
# export STINKY_HELIUS_API_KEY=your_key
# or STINKY_SOLANA_RPC_URL / STINKY_SOLANA_WS_URL

stinky-sentinel
# or: python -m sentinel.cli
```

## Config (env)

| Variable | Default | Notes |
|----------|---------|--------|
| `STINKY_SOLANA_RPC_URL` | public mainnet | Prefer Helius/QuickNode |
| `STINKY_SOLANA_WS_URL` | public mainnet WS | |
| `STINKY_HELIUS_API_KEY` | unset | When set, uses Helius HTTP+WS |
| `STINKY_REDIS_URL` | `redis://localhost:6380/0` | Host port 6380 |
| `STINKY_EVENT_LOG_URL` | `http://localhost:8001` | Optional HTTP ingest |

## Quality Gate

- [x] Production structure
- [x] Unit tests (parser)
- [x] Config + logging
- [x] Dedup of seen signatures
- [x] Reconnect with backoff
- [x] Publishes into existing event pipeline
- [x] Creator history enrichment (V1 proxy)

## Next

- Persist launches into our own `events` table via Event Log (already wired)
- Expand history to real launch index once we have enough events
- Entity resolution on deployer wallets
- Deterministic Stinky Score on the enriched profile
