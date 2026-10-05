from pathlib import Path


def test_asof_dataset_contract_is_leakage_explicit() -> None:
    source = (Path(__file__).parents[1] / "scripts" / "export_intelligence_asof_dataset.py").read_text(encoding="utf-8")
    assert 'DATASET_VERSION = "post-migration-asof-v1"' in source
    assert 'DEFAULT_HORIZON_SEC = 60' in source
    assert "ms.captured_at <= l.cutoff_at" in source
    assert "mb.bought_at <= l.cutoff_at" in source
    assert "el.observed_at <= l.cutoff_at" in source
    assert 'row["outcome_trade_signal"]' in source
    assert 'row["outcome_predictive_authority"]' in source
    assert "leakage invariant violated" in source
