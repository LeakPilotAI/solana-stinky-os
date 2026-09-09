from copy import deepcopy

from stinky_api.release_gate_aggregator import evaluate_release_gate


def _evidence():
    corpus = {
        "status": "OBSERVED",
        "representative": True,
        "sample_count": 100,
        "as_of": "2026-09-09T00:00:00+00:00",
        "temporal_cutoff_enforced": True,
        "live_execution": False,
        "trading_authority": False,
        "trade_signal": False,
    }
    calibration = {
        "status": "CALIBRATED_EMPIRICAL",
        "calibrated_horizons": ["15m", "1h"],
        "future_evidence_used_in_t0_decisions": False,
        "live_execution": False,
        "trading_authority": False,
        "trade_signal": False,
    }
    walk_forward = {
        "status": "OBSERVED",
        "release_gate_passed": True,
        "release_gate_result": "PASS",
        "live_canary_unlocked": False,
        "live_execution": False,
        "trading_authority": False,
        "trade_signal": False,
    }
    infrastructure = {
        "status": "HEALTHY",
        "critical_services_healthy": True,
        "unresolved_critical_incidents": 0,
        "live_execution": False,
        "trading_authority": False,
        "trade_signal": False,
    }
    safety = {
        "status": "OBSERVED",
        "safety_checks_complete": True,
        "unresolved_safety_failures": [],
        "live_execution": False,
        "trading_authority": False,
        "trade_signal": False,
    }
    return corpus, calibration, walk_forward, infrastructure, safety


def _run(*, mutate=None, policy_version="release-v1"):
    evidence = list(_evidence())
    if mutate:
        mutate(evidence)
    return evaluate_release_gate(*evidence, policy_version=policy_version)


def test_pass_only_marks_canary_review_eligible():
    result = _run()
    assert result["status"] == "OBSERVED"
    assert result["release_gate_result"] == "PASS"
    assert result["eligible_for_isolated_canary_review"] is True
    assert result["live_canary_unlocked"] is False
    assert result["automatic_canary_activation"] is False
    assert result["live_execution"] is False
    assert result["trading_authority"] is False
    assert result["next_step"] == "HUMAN_RELEASE_REVIEW_FOR_ISOLATED_CANARY"


def test_walk_forward_failure_is_observed_blocked_not_unknown():
    def mutate(items):
        items[2]["release_gate_passed"] = False
        items[2]["release_gate_result"] = "FAIL"

    result = _run(mutate=mutate)
    assert result["status"] == "OBSERVED"
    assert result["release_gate_result"] == "BLOCKED"
    assert result["eligible_for_isolated_canary_review"] is False
    assert "walk_forward_expectancy_after_costs" in result["blockers"]
    assert result["next_step"] == "REMAIN_PAPER_ONLY"


def test_unresolved_safety_failure_blocks_release():
    def mutate(items):
        items[4]["unresolved_safety_failures"] = ["temporal_leak"]

    result = _run(mutate=mutate)
    assert result["status"] == "OBSERVED"
    assert result["release_gate_result"] == "BLOCKED"
    assert "unresolved_safety_failures" in result["blockers"]


def test_unhealthy_infrastructure_fails_closed_unknown():
    def mutate(items):
        items[3]["critical_services_healthy"] = False

    result = _run(mutate=mutate)
    assert result["status"] == "UNKNOWN"
    assert "critical_services_healthy" in result["missing"]
    assert result["eligible_for_isolated_canary_review"] is False


def test_unresolved_critical_incident_fails_closed_unknown():
    def mutate(items):
        items[3]["unresolved_critical_incidents"] = 1

    result = _run(mutate=mutate)
    assert result["status"] == "UNKNOWN"
    assert "zero_unresolved_critical_incidents" in result["missing"]


def test_nonrepresentative_or_temporally_unsafe_corpus_fails_closed():
    def mutate(items):
        items[0]["representative"] = False
        items[0]["temporal_cutoff_enforced"] = False

    result = _run(mutate=mutate)
    assert result["status"] == "UNKNOWN"
    assert "representative_corpus" in result["missing"]
    assert "corpus_temporal_cutoff" in result["missing"]


def test_uncalibrated_probability_evidence_fails_closed():
    def mutate(items):
        items[1]["status"] = "UNKNOWN"
        items[1]["calibrated_horizons"] = []

    result = _run(mutate=mutate)
    assert result["status"] == "UNKNOWN"
    assert "calibrated_empirical_probability_evidence" in result["missing"]
    assert "calibrated_horizons" in result["missing"]


def test_authority_contamination_fails_closed():
    def mutate(items):
        items[1]["trading_authority"] = True

    result = _run(mutate=mutate)
    assert result["status"] == "UNKNOWN"
    assert result["authority_contamination"] == ["calibration"]
    assert "non_authoritative_release_evidence" in result["missing"]


def test_policy_version_is_required():
    result = _run(policy_version="")
    assert result["status"] == "UNKNOWN"
    assert "release_policy_version" in result["missing"]


def test_evidence_is_frozen_from_later_mutation():
    corpus, calibration, walk_forward, infrastructure, safety = _evidence()
    result = evaluate_release_gate(
        corpus,
        calibration,
        walk_forward,
        infrastructure,
        safety,
        policy_version="release-v1",
    )
    original = deepcopy(result["evidence"])
    corpus["sample_count"] = 0
    calibration["calibrated_horizons"].clear()
    safety["unresolved_safety_failures"].append("later")
    assert result["evidence"] == original
