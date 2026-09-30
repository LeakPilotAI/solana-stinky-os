from stinky_api.paper_policy_provisioning import validate_paper_configuration, _evidence_provenance, provision_evidence_backed_paper_policy


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
    candidate = {
        "status": "PAPER_CANDIDATE_ARTIFACT",
        "candidate_version": "score-paper-candidate-v1:abc",
        "evidence_sha256": "a" * 64,
        "payload": {"evaluation_as_of": "2026-09-30T00:00:00+00:00"},
    }
    from stinky_api.paper_runtime_worker import canonical_sha256
    candidate["payload"].update(schema_version="score-paper-candidate-v1", selected_threshold=55)
    candidate["evidence_sha256"] = canonical_sha256(candidate["payload"])
    candidate["candidate_version"] = "score-paper-candidate-v1:" + candidate["evidence_sha256"][:16]
    readiness = {
        "readiness_status": "READY_FOR_PAPER_POLICY_REVIEW",
        "candidate_version": candidate["candidate_version"],
        "evidence_sha256": candidate["evidence_sha256"],
        "candidate_cutoff": candidate["payload"]["evaluation_as_of"],
        "comparison_as_of": "2026-10-01T00:00:00+00:00",
        "criteria": {"min_later_sample": 20},
        "checks": {"sufficient_later_sample": True},
    }
    from stinky_api.prospective_score_paper_candidate import AUTHORITY as candidate_authority
    from stinky_api.prospective_score_candidate_readiness import AUTHORITY as readiness_authority
    candidate.update(candidate_authority)
    readiness.update(readiness_authority)
    provenance = _evidence_provenance(candidate, readiness)
    assert provenance is not None
    assert provenance["evidence_backed"] is True
    assert provenance["candidate_version"] == candidate["candidate_version"]
    assert provenance["candidate_evidence_sha256"] == candidate["evidence_sha256"]
    assert len(provenance["provenance_sha256"]) == 64
    mismatched = dict(readiness, evidence_sha256="b" * 64)
    assert _evidence_provenance(candidate, mismatched) is None
    wrong_cutoff = dict(readiness, candidate_cutoff="2026-09-29T00:00:00+00:00")
    assert _evidence_provenance(candidate, wrong_cutoff) is None


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
