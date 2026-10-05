# Genesis Intelligence Feature Audit v1

Descriptive research only. No live admission, alert, or trading behavior changes.

T+30 is rejected for scoring research because market coverage is incomplete and HELD coverage is 0%. T+60 is the earliest horizon with 100% market coverage across all 86 canonical labels. T+120 is retained as a stability comparison.

At T+60 buyer SOL-spend coverage is RUNNER 24.1%, HELD 16.7%, FADE 11.1%, so missing buyer evidence remains UNKNOWN and cannot be a required scoring feature.

Market-cap regimes at T+60: low <= about $46.8k (11 RUNNER, 18 FADE, 0 HELD); mid about $46.8k-$380.2k (14 RUNNER, 14 FADE, 0 HELD); high > about $380.2k (4 RUNNER, 13 FADE, 12 HELD). HELD is currently entirely high-regime, so global comparisons are confounded by market size.

RUNNER vs FADE Cliff's delta at T+60: low regime market cap -0.596, liquidity -0.537, 5m volume -0.414, early buyers +0.374; mid regime market cap -0.204, liquidity -0.286, 5m volume -0.235, early buyers -0.071; high regime market cap +0.269, liquidity +0.231, 5m volume +0.231, but only 4 RUNNER examples.

Acceptance rules: no global linear score across regimes; T+60 is the default research horizon; missing evidence is UNKNOWN; features require adequate coverage and stable within-regime direction; high-regime RUNNER evidence is insufficient; no ML training yet; first scoring proposal must be transparent and shadow/paper only.
