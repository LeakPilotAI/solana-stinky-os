# Genesis coordination (intel-v2.0.0)

Assembler, not a second brain. Not a buy.

## Data flow

```
DexScreener / Solana WS
  → Sentinel (MigrationWatcher, HighVolumeDiscovery, VolumeMonitor)
  → Gate 1 ($33k / 5m, clamp $200k)
  → intelligence_investigations (correlation_id)
  → market_observations (ticks T+0 … T+1800)
  → quality_states
  → wallet_observations / entities
  → outcomes (after the window)
  → pattern_fingerprints / analogues / recipes
  → Command Center synthesis (desk rows)
  → Token page case file (`GET /v1/coordination/{mint}`)
  → Alert policy (state change, not price tick)
  → Discord (POLICY FIRED ≠ SENT)
```

## Canonical identity

`correlation_id = mint:gate1_at`

## Evidence

Each atom: what, value, source, observed_at, as_of, quality
(`LIVE|FIXTURE|SIMULATION|HISTORICAL`), unknown_reason.
`calibrated_probability = false`.

## Lifecycle

DISCOVERED → QUALIFIED → INVESTIGATING → WATCHING → ANALYZING → COMPLETED
FAILED | INTERRUPTED | INCOMPLETE | UNKNOWN

## Tab views of the same case

| Tab | Role |
|---|---|
| Command Center | synthesis |
| Tokens | market context + case file |
| Investigations | permanent rows |
| Observations | T+ path |
| Entities / Wallets | who |
| Quality / Dips | setup state |
| Recipes / Analogues | historical comparison |
| Unknown | missing evidence |
| Operator | runtime |
| Discord | notify state changes |

## Boundaries

- SIMULATION never LIVE
- Future ticks hidden at as_of
- ATLAS isolated (ports, compose project, stop scripts)
- No paper trading, no execution, no ML in this milestone
- Runtime: health ping does not `_reset()` Redis
