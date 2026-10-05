from pathlib import Path

ROOT=Path(__file__).parents[1]

def test_docker_export_is_bounded_and_reuses_leakage_query():
    t=(ROOT/"scripts"/"export_intelligence_asof_dataset_docker.py").read_text(encoding="utf-8")
    assert "QUERY" in t
    assert '"docker","exec","-i"' in t
    assert "timeout=60" in t
    assert '"docker-local-psql"' in t

def test_calibration_profiles_are_evidence_only_and_sample_gated():
    t=(ROOT/"scripts"/"build_intelligence_calibration_profiles.py").read_text(encoding="utf-8")
    assert '"historical-calibration-v1"' in t
    assert '"authority":"evidence_only"' in t
    assert '"trade_signal":False' in t
    assert '"predictive_authority":False' in t
    assert 'counts["RUNNER"]>=10 and counts["FADE"]>=10' in t
    assert '"INCLUDE","WATCH"' in t
