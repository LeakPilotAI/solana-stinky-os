# Genesis Intelligence Engine — As-Of Dataset v1

Purpose: descriptive/calibration research only. Do not train or deploy a trading model from this dataset yet.

Decision horizon: T+60 seconds after `migration_at`.

Leakage contract:
- market snapshot must have `captured_at <= cutoff_at`
- migration buyers must have `bought_at <= cutoff_at`
- entity launch evidence must have `observed_at <= cutoff_at`
- canonical measured outcome is stored only as a future label and is never a feature
- unknown buyer/entity evidence remains unknown/zero-count; it is not inferred from later evidence

Current live export (2026-10-05):
- 86 canonical labeled tracks
- RUNNER 29
- HELD 12
- FADE 45
- T+60 market snapshot coverage 86/86

Initial descriptive medians at T+60:
- RUNNER: liquidity $18,980.18; 5m volume $3,561.83; market cap $50,884
- HELD: liquidity $304,916.76; 5m volume $143,052.83; market cap $11,178,949.50
- FADE: liquidity $54,203.71; 5m volume $17,984.53; market cap $52,714

Interpretation: this sample contains strong market-size/regime differences. These are observations, not causal or predictive claims. Feature coverage and regime stratification must be audited before any score weighting.
