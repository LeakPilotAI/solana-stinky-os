from stinky_api.runner_impostor_comparison import compare_runner_vs_impostor


def _record(label: str, adversarial: bool, *, mint: str, feature_snapshot: dict):
    return {
        "status": "OBSERVED",
        "mint": mint,
        "feature_snapshot": feature_snapshot,
        "outcome": {"label": label},
        "adversarial_case": adversarial,
        "temporal_cutoff_enforced": True,
        "future_evidence_used_in_t0_features": False,
    }


def test_compares_only_frozen_t0_features_between_observed_cohorts():
    result = compare_runner_vs_impostor([
        _record("RUNNER", False, mint="runner", feature_snapshot={"cohort_seen": False, "basis": "market"}),
        _record("FADE", True, mint="fade", feature_snapshot={"cohort_seen": True, "basis": "market"}),
    ])

    assert result["status"] == "OBSERVED"
    assert result["runner_count"] == 1
    assert result["impostor_count"] == 1
    assert result["outcomes_used_only_for_cohort_assignment"] is True
    assert result["future_evidence_used_as_feature"] is False
    by_feature = {row["feature"]: row for row in result["comparisons"]}
    assert by_feature["cohort_seen"]["observed_difference"] is True
    assert by_feature["basis"]["observed_difference"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
    assert result["causal_claim"] is False


def test_unknown_without_both_observed_cohorts():
    result = compare_runner_vs_impostor([
        _record("RUNNER", False, mint="runner", feature_snapshot={"x": 1}),
    ])
    assert result["status"] == "UNKNOWN"
    assert result["missing"] == ["observed_impostor_cases"]


def test_excludes_temporally_unsafe_or_unknown_records():
    unsafe = _record("FADE", True, mint="unsafe", feature_snapshot={"x": 2})
    unsafe["future_evidence_used_in_t0_features"] = True
    unknown = {"status": "UNKNOWN", "mint": "unknown", "feature_snapshot": {"x": 3}}
    result = compare_runner_vs_impostor([
        _record("RUNNER", False, mint="runner", feature_snapshot={"x": 1}),
        unsafe,
        unknown,
    ])
    assert result["status"] == "UNKNOWN"
    assert result["impostor_count"] == 0
    assert result["excluded_count"] == 2


def test_held_cases_do_not_enter_runner_or_impostor_cohorts():
    result = compare_runner_vs_impostor([
        _record("RUNNER", False, mint="runner", feature_snapshot={"x": 1}),
        _record("FADE", True, mint="fade", feature_snapshot={"x": 2}),
        _record("HELD", False, mint="held", feature_snapshot={"x": 1}),
    ])
    assert result["status"] == "OBSERVED"
    assert result["runner_count"] == 1
    assert result["impostor_count"] == 1
    assert result["excluded_count"] == 1


def test_only_features_present_in_every_included_case_are_compared():
    result = compare_runner_vs_impostor([
        _record("RUNNER", False, mint="r", feature_snapshot={"shared": 1, "runner_only": 7}),
        _record("FADE", True, mint="f", feature_snapshot={"shared": 2, "fade_only": 9}),
    ])
    assert result["status"] == "OBSERVED"
    assert [row["feature"] for row in result["comparisons"]] == ["shared"]
