# Stinky Filter Engine — volume-first-v1.0.0 + inspect-v1.1.0-harden

## Purpose

Single canonical **admission** decision for every opportunity / alert path.

API: `evaluate_market(market) -> EligibilityResult`

Gate 1 is an **investigation trigger**, not a buy signal.

```
eligible: bool   # Gate 1 passed
failed_filters: []
passed_filters: []
normalized_metrics: {}
source_metadata: {}
reason_codes: []
```

Filtering happens **before** scoring. A Stinky Score of 99 cannot override a failed Gate 1.

## Gate 1 (required)

| Gate | Default | Fail closed on missing? | Reason code |
|------|---------|-------------------------|-------------|
| Protocol allowlist | pump + listed launchpads; deny raydium/meteora/orca/pumpAmm | Yes | PROTOCOL_DISABLED / PROTOCOL_UNKNOWN |
| Valid mint | non-empty | Yes | INVALID_MINT |
| Migrated tab | migrated | Yes | NOT_MIGRATED |
| 5m volume | ≥ **$150,000** (configurable up to $200,000; higher config is clamped) | Yes | VOLUME_BELOW_MIN / VOLUME_UNKNOWN |

`FilterConfig.min_volume_usd` and `evaluate_gate1(min_volume_usd=…)` never
silently honor a threshold above $200,000.

## Not Gate 1

| Signal | Role |
|--------|------|
| Global fees | Optional evidence via FeeResolver. Unknown does **not** reject. |
| Liquidity | Recorded; used in inspection / rug model |
| Market cap | Recorded |
| Social | Recorded; not required |
| Creator / wallets / patterns | Investigation only |

## Investigation (after Gate 1)

`investigate()` (`intel-v1.1.0-harden`, `inspect-v1.1.0-harden`):

| Component | UNKNOWN vs LOW |
|-----------|----------------|
| Synthetic | UNKNOWN unless ≥3 independent flow signals (must include concentration or diversity) **or** a risk finding on partial data |
| Rug | UNKNOWN when there are no risk findings. Unknown creator is missing, not a hit |
| Wallets | UNKNOWN with no buyers; OBSERVED without sample≥3 history; KNOWN only with smart-money evidence |
| Patterns | UNKNOWN without inputs; structural matches are decision-time only |
| Runner potential | 0–100 score. `calibrated_probability = false`. Not a probability |
| Stinky Score | Base 50 + labeled components. Weights unchanged. Volume is a component, not the score |

Pipeline: `REJECTED` → `DISCOVERED` → `INVESTIGATING` → `UNKNOWN` / `QUALIFIED` / `HIGH_RISK` / `ALERT`.

QUALIFIED is “has stored intelligence, not high-risk.” It is not “safe” and not an alert.

## Alert policy

`can_alert` / `can_alert_investigation` after Gate 1:

- inspection complete
- synthetic and rug not CRITICAL
- meaningful intelligence (stored smart-money sample ≥ 3 **or** known creator)
- score ≥ 55

Volume alone cannot alert. UNKNOWN / insufficient evidence never promotes
(`promote=false`). A score without stored wallet or creator history is
diagnostic only — it is not a reason to like the CA.

Pattern resemblance and co-buy links are as-of-decision (ADR-012). Sample
floors: smart money ≥ 3 resolved tokens; creator KNOWN ≥ 3 launches;
fingerprint resemblance ≥ 5 prior prints. Below that: UNKNOWN. Unique-wallet counts are not intelligence.

## Authoritative fee metric (optional)

**Name:** `global_fees_sol`

Resolver: `stinky_core.fees.FeeResolver` (`fee-resolver-v1.0.0`). See ADR-009
and ADR-010. UNKNOWN does **not** fail Gate 1 (ADR-011).

When unknown: `global_fees_sol = NULL`, `fee_status = UNKNOWN`. Never label unknown as zero.

## Reason codes

`VOLUME_BELOW_MIN` `VOLUME_UNKNOWN` `PROTOCOL_DISABLED` `PROTOCOL_UNKNOWN` `NOT_MIGRATED` `INVALID_MARKET_DATA` `INVALID_MINT` `FEES_BELOW_MIN` `FEES_UNKNOWN` (legacy / optional-fees profile) `INSPECTION_INCOMPLETE` `RISK_CRITICAL` `INTELLIGENCE_INSUFFICIENT` `SCORE_BELOW_MIN`

## Layers

1. **Gate 1** (`evaluate_gate1` / `qualify_fresh_pump_migration`) — mint + protocol + migrated + 5m volume.
2. **Deep inspection** (`stinky_core.inspect` + `stinky_core.intelligence.investigate`).
3. **Intelligence gate** (`can_alert_investigation`) — only after inspection.

Discovery resolves fees **after** Gate 1. Discord / replay / backtest consume the same gate.

## Backtest

`stinky_core.backtest.backtest_candidates` (`stinky-backtest-v1.1.0-harden`):

- unique mint
- `decision_time_snapshot` strips peak/outcome and future wallet/pattern fields
- investigate
- alert
- outcome labels from future observations only after the decision

Reported: `unique_candidates`, `gate1_passed`, `investigated`, `qualified`,
`alerts`, `runners`, `held`, `fades`, `unknown`, `precision`, `coverage`,
`false_positive_rate`, sample sizes.

Never optimize thresholds from a tiny sample.

## Unknown semantics

Missing required Gate 1 data → reject.
Missing investigation data → UNKNOWN.
UNKNOWN is never rendered as pass/green/safe.
