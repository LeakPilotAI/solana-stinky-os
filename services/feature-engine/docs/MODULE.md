# Module: feature-engine (v0.1.0)

**Status:** Production-ready foundation  
**Date:** 2026-08-10  

## Scope delivered

- Versioned feature definitions (ADR-006)
- Feature set `fs-v1.0.0-launch-basic` with 8 deterministic features:
  - launch_count, bond_rate, median_ath_multiple, rug_count
  - wallet_age_days, unique_funding_sources, repeat_buyer_ratio, has_rug_history
- `FeatureEngine` that updates entity context, materializes vectors, persists to `features` table
- Fully explainable / deterministic (ADR-005)
- Unit tests for definitions and vector computation
- Configuration via pydantic-settings

## Design notes

- Context is currently in-memory for V1 speed; production will load projections from Postgres.
- Feature set hash is stored with every row so Score / Prediction engines can pin exact versions.
- No ML. Statistical and counting features only.

## Quality Gate

- [x] Production code
- [x] Unit tests
- [x] Documentation
- [x] Versioned features
- [x] Deterministic
- [x] Configuration + logging hooks

## Next module

Entity Resolution Engine (wallet clustering → Entity nodes with confidence).
