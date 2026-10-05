from pathlib import Path

def test_feature_audit_is_descriptive_and_regime_aware():
    t=(Path(__file__).parents[1]/"scripts"/"audit_intelligence_asof_dataset.py").read_text(encoding="utf-8")
    assert '"asof-feature-audit-v1"' in t
    assert "cliffs_delta" in t
    assert '"low"' in t and '"mid"' in t and '"high"' in t
    assert "outcome_label" in t
    assert "score" not in t.lower()
