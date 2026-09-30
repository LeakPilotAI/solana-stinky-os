from copy import deepcopy

from stinky_api.paper_policy_provisioning import (
    validate_paper_configuration,
    _evidence_provenance,
    provision_evidence_backed_paper_policy,
)
from stinky_api.prospective_score_candidate_readiness import assess_post_candidate_readiness


def valid_config():
    return {
        "paper_policy": {
            "policy_version": "paper-v1",
            "horizon": "15m",
            "min_runner_probability": 0.6,
            "max_fade_probability": 0.25,
            "min_nonnegative_market_cap_probability": 0.7,
        },
        "execution_assumptions": {
            "entry_slippage_bps": 100,
            "exit_slippage_bps": 100,
            "entry_fee_bps": 50,
            "exit_fee_bps": 50,
            "latency_ms": 500,
        },
        "paper_notional_usd": 20,
    }


def _candidate():
    candidate = {
        "status": "PAPER_CANDIDATE_ARTIFACT",
        "candidate_version": "score-paper-candidate-v1:abc",
        "evidence_sha256": "a" * 64,
        "payload": {
            "evaluation_as_of": "2026-09-30T00:00:00+00:00",
            "schema_version": "score-paper-candidate-v1",
            "selected_threshold": 55,
        },
    }
    from stinky_api.paper_runtime_worker import canonical_sha256
    candidate["evidence_sha256"] = canonical_sha256(candidate["payload"])
    candidate["candidate_version"] = "score-paper-candidate-v1:" + candidate["evidence_sha256"][:16]
    from stinky_api.prospective_score_paper_candidate import AUTHORITY as candidate_authority
    candidate.update(candidate_authority)
    return candidate


def _comparison(candidate):
    return {
        "status":"OBSERVED",
        "comparison_status":"PROSPECTIVE_COMPARISON_COMPLETE",
        "candidate_version":candidate["candidate_version"],
        "evidence_sha256":candidate["evidence_sha256"],
        "candidate_threshold":55.0,
        "candidate_cutoff":candidate["payload"]["evaluation_as_of"],
        "as_of":"2026-10-01T00:00:00+00:00",
        "sample_count":20,
        "runner_count":5,
        "negative_count":15,
        "unknown_score_count":1,
        "unknown_score_rate":0.05,
        "actionable_score_count":19,
        "actionable_score_rate":0.95,
        "non_actionable_numeric_score_count":0,
        "non_actionable_numeric_score_rate":0.0,
        "score_threshold_metrics":{
            "universe":"numeric_score","eligible_count":19,"runner_count":5,"negative_count":14,
            "positive_count":5,"runner_precision":0.8,"false_discovery_rate":0.2,
            "false_positive_rate":1/14,"runner_recall":0.8,"missed_runner_count":1,
        },
        "actionable_score_threshold_metrics":{
            "universe":"actionable_score","eligible_count":19,"runner_count":5,"negative_count":14,
            "positive_count":5,"runner_precision":0.8,"false_discovery_rate":0.2,
            "false_positive_rate":1/14,"runner_recall":0.8,"missed_runner_count":1,
        },
        "actual_alert_admission_metrics":{
            "universe":"all_labeled","eligible_count":20,"runner_count":5,"negative_count":15,
            "positive_count":4,"runner_precision":0.75,"false_discovery_rate":0.25,
            "false_positive_rate":1/15,"runner_recall":0.6,"missed_runner_count":2,
        },
        "missing":[],
    }


def _readiness(candidate):
    return assess_post_candidate_readiness(
        _comparison(candidate),
        min_later_sample=20,
        min_later_runners=5,
        min_later_negatives=15,
        min_actionable_score_rate=0.9,
        min_actionable_positive_count=5,
        min_actionable_runner_precision=0.75,
        max_actionable_false_discovery_rate=0.25,
        max_actionable_false_positive_rate=0.1,
        min_actionable_runner_recall=0.8,
        max_actionable_missed_runners=1,
    )


def test_valid_policy_is_deterministically_versioned_and_non_live():
    a = validate_paper_configuration(valid_config())
    b = validate_paper_configuration(valid_config())
    assert a["status"] == "VALIDATED"
    assert a["policy_sha256"] == b["policy_sha256"]
    assert len(a["policy_sha256"]) == 64
    assert a["live_execution"] is False
    assert a["trading_authority"] is False
    assert a["order_submitted"] is False
    assert a["wallet_mutated"] is False


def test_missing_thresholds_fail_closed_instead_of_defaulting():
    config = valid_config()
    config["paper_policy"]["min_runner_probability"] = None
    result = validate_paper_configuration(config)
    assert result["status"] == "UNKNOWN"
    assert "min_runner_probability" in result["missing"]


def test_notional_above_twenty_is_rejected():
    config = valid_config()
    config["paper_notional_usd"] = 20.01
    result = validate_paper_configuration(config)
    assert result["status"] == "UNKNOWN"
    assert "paper_notional_usd" in result["missing"]


def test_unknown_horizon_is_rejected():
    config = valid_config()
    config["paper_policy"]["horizon"] = "2h"
    result = validate_paper_configuration(config)
    assert result["status"] == "UNKNOWN"
    assert "horizon" in result["missing"]


def test_manual_policy_is_explicitly_not_evidence_backed():
    result = validate_paper_configuration(valid_config())
    assert result["configuration"]["provenance"] == {"mode": "MANUAL_OPERATOR_SUPPLIED", "evidence_backed": False}


def test_evidence_provenance_requires_exact_candidate_readiness_identity():
    candidate = _candidate()
    readiness = _readiness(candidate)
    assert readiness["readiness_status"] == "READY_FOR_PAPER_POLICY_REVIEW"
    provenance = _evidence_provenance(candidate, readiness)
    assert provenance is not None
    assert provenance["evidence_backed"] is True
    assert provenance["candidate_version"] == candidate["candidate_version"]
    assert provenance["candidate_evidence_sha256"] == candidate["evidence_sha256"]
    assert provenance["comparison_evidence_sha256"] == readiness["comparison_evidence_sha256"]
    assert len(provenance["provenance_sha256"]) == 64

    mismatched = dict(readiness, evidence_sha256="b" * 64)
    assert _evidence_provenance(candidate, mismatched) is None
    wrong_cutoff = dict(readiness, candidate_cutoff="2026-09-29T00:00:00+00:00")
    assert _evidence_provenance(candidate, wrong_cutoff) is None


def test_evidence_provenance_rejects_tampered_or_unbound_comparison_evidence():
    candidate = _candidate()
    readiness = _readiness(candidate)

    tampered = deepcopy(readiness)
    tampered["comparison_evidence"]["actionable_score_threshold_metrics"]["runner_precision"] = 0.0
    assert _evidence_provenance(candidate, tampered) is None

    wrong_hash = dict(readiness, comparison_evidence_sha256="b" * 64)
    assert _evidence_provenance(candidate, wrong_hash) is None

    forged_checks = deepcopy(readiness)
    forged_checks["comparison_evidence"]["actionable_score_threshold_metrics"]["runner_recall"] = 0.0
    from stinky_api.paper_evidence_json import content_sha256
    forged_checks["comparison_evidence_sha256"] = content_sha256(forged_checks["comparison_evidence"])
    assert _evidence_provenance(candidate, forged_checks) is None


def test_evidence_backed_provisioning_defaults_to_non_activation():
    import inspect
    params = inspect.signature(provision_evidence_backed_paper_policy).parameters
    assert params["activate"].default is False


def test_operator_provisioning_cli_defaults_to_provision_only_and_requires_explicit_activation():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[3] / "scripts" / "provision_paper_policy.py").read_text(encoding="utf-8")
    assert 'mode.add_argument("--activate", action="store_true"' in source
    assert 'activate=bool(args.activate)' in source
    assert 'activate=not args.provision_only' not in source
    assert "provision-only is already the safe default" in source
