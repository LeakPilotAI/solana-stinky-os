# Stinky Filter Engine — axiom-parity-v1.0.0

## Purpose

Single canonical **admission** decision for every opportunity / alert path.

Filtering happens **before** scoring. A Stinky Score of 99 cannot override a failed hard gate.

## Critical rule

> If `global_fees_sol` is unavailable or cannot be authoritatively verified, **REJECT** the token. Never treat missing fee data as passing.

## Hard gates (all must pass)

| Gate | Default | Fail closed on missing? |
|------|---------|-------------------------|
| Protocol allowlist | pump + listed launchpads; deny raydium/meteora/orca/… | Yes (unknown → reject) |
| Global fees | ≥ **5.0 SOL** | **Yes** |
| Liquidity | ≥ **8 USD** | Yes |
| Volume | ≥ **$100,000** | Yes |
| Market cap | ≥ **$31,333** | Yes |
| Social | ≥ 1 verified presence | Yes |

Config knobs (env / settings):

- `STINKY_MIN_FEES_SOL` (default 5.0)
- `STINKY_MIN_LIQUIDITY_USD` (default 8)
- `STINKY_MIN_VOLUME_USD` (default 100000)
- `STINKY_MIN_MARKET_CAP_USD` (default 31333)
- `STINKY_FILTER_VERSION` = `axiom-parity-v1.0.0`

## Authoritative fee metric

**Name:** `global_fees_sol`

**Meaning:** Cumulative / all-time fees associated with the token on pump.fun, expressed in SOL.

**Source (current):** pump.fun public coin API

- `https://frontend-api-v3.pump.fun/coins/{mint}`
- `https://frontend-api.pump.fun/coins/{mint}`

**Fields tried (in order):** `total_fees`, `total_fees_sol`, `fees_sol`, `fee_sol`, `creator_fees_sol`, `accumulated_fees` (and nested under `coin` / `data` / `result`).

**Unit normalization:** if a raw numeric value is `> 1_000_000`, treat as lamports and divide by `1e9`. Otherwise treat as SOL.

**Provenance fields (required when used for admission):**

- `global_fees_sol`
- `global_fees_source` (e.g. `pump.fun/total_fees`)
- `global_fees_timestamp`
- `global_fees_confidence`
- `global_fees_raw`
- `global_fees_verified` — must be **true** for admission

**Not acceptable substitutes:** transaction fee, priority fee, one-tx fee, LP fee alone, DexScreener fee estimate, liquidity, volume, market cap.

## Layers

1. **Early gate** (`qualify_fresh_pump_migration`) — mint + DEX + fees only. Used when ALERT_CANDIDATE is emitted and only fees are known.
2. **Full admission** (`StinkyFilterEngine.evaluate` / `evaluate_admission`) — all hard gates. Required before Discord alert, Live Runners opportunity surface, and scored opportunity queue.

## Invariants

1. `global_fees_verified != true` → cannot alert  
2. `global_fees_sol < 5` (default) → cannot alert  
3. liquidity / volume / mcap below floor → cannot alert  
4. no verified social → cannot alert  
5. unsupported protocol → cannot alert  
6. failed hard filter → score cannot override  
7. rejected → not in Live Runners opportunity / Opportunity Queue / Discord  

## Versioning

Profile id: `axiom-parity-v1.0.0`  

Future profiles (`stinky-alpha-v1`, etc.) should be new configs, not mutations of this profile, so backtests remain reproducible.
