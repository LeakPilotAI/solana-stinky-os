from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_formal_validation_preflight_is_fail_closed_and_non_activating():
    t=(ROOT/"scripts"/"formal_paper_validation_preflight.py").read_text()
    assert '"thresholds_invented":False' in t
    assert '"automatic_activation":False' in t
    assert '"performance_validation":False' in t
    assert "no_active_immutable_paper_policy" in t
    assert "no_first_class_policy_cohort_records" in t
    assert "no_closed_paper_simulations" in t
    assert "READY_FOR_CRITERIA_BOUND_VALIDATION" in t
    assert "INSERT " not in t and "UPDATE " not in t and "DELETE " not in t
def test_formal_validation_launcher_treats_not_ready_as_evidence():
    t=(ROOT/"Run-Formal-Paper-Validation-Preflight.cmd").read_text()
    assert "formal_paper_validation_preflight.py" in t
    assert 'if "%ERR%"=="2"' in t
