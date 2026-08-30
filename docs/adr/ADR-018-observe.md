# ADR-018 Live observation + runner recipes

Status: Accepted
Date: 2026-08-30

## Decision

Every Gate-1 mint becomes an immutable investigation record plus an observation window of stored market ticks (T+0 through T+1800, including T+15). Later ticks never overwrite Gate-1 fields and never leak into the original fingerprint or score.

Runner recipes compare the current 10-band fingerprint to historical analogues as-of. They report RUNNER / HELD / FADE / UNKNOWN counts and observed shared bands. They are not probabilities. Sample < 5 stays UNKNOWN.

Candidate insights count pattern occurrence by outcome on development rows only. Holdout is excluded. Insights never auto-promote into scoring.

## Not changed

- Gate 1 remains $150k default, $200k clamp
- Fees remain optional evidence
- Score weights unchanged; volume_component = 0
- Reputation floors unchanged
- Fingerprint KEY remains 10 bands
- calibrated_probability = false
- No ML, no Neo4j

## Watch loop

Investigate once at first Gate 1 pass. Keep polling until max_watch (1800s) to persist follow-up ticks even after an alert. Missing fields stay None. No interpolation.
