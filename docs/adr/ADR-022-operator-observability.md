# ADR-022 Operator observability (intel-v1.11.0)

Status: Accepted
Date: 2026-08-30

## Decision

intel-v1.11.0-operator makes the existing Genesis path visible. It does not add a new brain.

The operator box must show, from persisted records only:

- SYSTEM STATUS
- LIVE DATA STATUS
- MIGRATION WATCH STATUS
- GATE STATUS ($150k / $200k clamp)
- ACTIVE INVESTIGATIONS
- ACTIVE WATCHES
- LAST OBSERVATION
- NEXT OBSERVATION
- QUALITY STATE
- DISCORD STATUS (policy vs delivery)
- DATABASE STATUS

Missing values display as UNKNOWN. LIVE / FIXTURE / SIMULATION / MOCK never mix.

## Discord

`should_alert` firing is POLICY FIRED. A Discord API success is DELIVERY SENT.
A send exception is FAILED. No channel and no subscribers is NOT ATTEMPTED.
Never report Discord as working merely because the policy function ran.

## Provider vs quality

A broken DexScreener/WS/Postgres probe is DATA QUALITY DEGRADATION.
It is not TOKEN QUALITY DETERIORATION.

## Restart

Sqlite in-process watch resume is proven in SIMULATION tests.
LIVE Postgres restart is only claimed after an actual start → stop → start on the operator box.

## Gate 1

Unchanged: $150,000 5-minute volume, $200,000 clamp.
NOT OBSERVED is not a failure. Do not lower the gate to manufacture a print.

## Not claimed

A live $150k Gate 1 print during this sandbox run unless one is actually stored with evidence_label LIVE.
