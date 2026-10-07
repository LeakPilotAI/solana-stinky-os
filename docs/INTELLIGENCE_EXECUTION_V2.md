# Execution V2 preregistration

Status: hypothesis specified; prospective registry boundary must be created by the freeze command before plans are admitted. No prospective V2 outcomes have been used to select these rules.

The supplied IE-9B 60-second historical result (13 fills, mean 0.9980x, median 1.0216x, 7 winners) motivates a single fixed-hold hypothesis, not a profitability claim. IE-9A demonstrates why incomplete windows cannot contribute extrema. No further hold search, peak-based exits, threshold search, or historical retuning is permitted.

## Frozen experiment

- Source: unchanged genesis-evidence-paper-v3 ENTER decisions, score strictly greater than 50. No change to V3 or its boundary.
- New version: genesis-paper-execution-v2. V1, its 30-second latency, 900-second hold, costs, rows and boundary remain immutable.
- Entry target: decision time plus 30 seconds. Plan must be durably registered before that target, with migration, score and decision at or after the registry boundary. Missed admission deadlines are not backfilled.
- Exit target: entry target plus 60 seconds, independent of observed price. No stop/peak/recovery-dependent exit.
- Price proxies: first finite positive snapshot at/after each target, within 30 seconds. Entry liquidity must be finite and at least $1,000. Missing or invalid evidence remains UNKNOWN; a not-yet-closed window remains PENDING. An observed low-liquidity entry is REJECTED, never a fill.
- Maturity: exit target plus 30 seconds. No partial-window return or extrema statistics.
- Paper notional $100; entry fee 0.5%, entry slippage 0.5%, exit fee 0.5%, exit slippage 0.5%. Net multiple = exit/entry * (1-exit fee-exit slippage)/(1+entry fee+entry slippage). These are frozen assumptions, not measured transaction costs or executable fills. Report actual observation delays and liquidity alongside P&L.
- Immutable policy hash, database-clock boundary, plan and terminal result; no update/delete, no relabeling, replay keyed by policy and source decision. Results must bind the exact policy/plan and source snapshot identities. A different configuration requires a different policy/version and a new future boundary.

## Adequacy declared before results

First evaluation only after at least 100 distinct-mint mature admitted plans across at least 5 explicitly recorded powered/running sessions, at least 80 complete priced paths, and no more than 20% UNKNOWN outcomes. Report every admitted plan and terminal status, missingness, rejections, cohort/session counts, observation delay and cost assumptions. These gates permit a descriptive paper evaluation; they do not establish profitability, statistical independence, calibration, competitor superiority, or permission for live capital. Avoid repeated significance checks or retuning after results. If gates fail, report insufficient evidence and continue the unchanged protocol.

No claimed completion percentage has a defensible denominator. Runtime collection, immutable result implementation and evaluation remain separate acceptance steps. Do not fabricate sessions, future observations, coverage, fills or results to complete this roadmap.

## Boundaries

The freeze registry obtains its boundary from PostgreSQL clock_timestamp on first insertion. Re-running freeze must return the same boundary and reject a changed policy hash. Documentation timestamps are not a deployment boundary. Existing evidence is never rewritten; retrospective IE-9B remains historical hypothesis-generation only. Genesis uses port 8010; Atlas 8000 is outside scope. All execution is PAPER-ONLY; no RPC, signing, wallets, order submission or live-money authority.
