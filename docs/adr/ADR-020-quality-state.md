# ADR-020 Quality state and quality dips

Status: Accepted
Date: 2026-08-30

## Decision

Quality state is a **post-Gate-1 observation label**. It is not Gate 1, not Stinky Score, and not a buy/sell.

States: UNKNOWN, HEALTHY, IMPROVING, STABLE, WATCH, DETERIORATING, SEVERE_DETERIORATION, FAILED.

A quality dip is a transition into WATCH / DETERIORATING / SEVERE_DETERIORATION / FAILED.

UI severity: CRITICAL (FAILED, SEVERE), WARNING (DETERIORATING), WATCH, RESOLVED (left a dip).

## Rules

- Only stored ticks. No interpolation. Future ticks after as_of are hidden.
- Only T+0 → UNKNOWN (insufficient later path).
- Changes inside a 15% noise band are ignored.
- Worst evidence wins (fail closed).
- Missing fields stay UNKNOWN and cannot invent a healthy call.
- calibrated_probability = false.
- Discord fires on **state change**, not on every tick. Same state is silent. Severity upgrade is a new alert.

## Not changed

Gate 1 $150k / $200k clamp. Score weights. Fingerprint KEY. Reputation floors.
