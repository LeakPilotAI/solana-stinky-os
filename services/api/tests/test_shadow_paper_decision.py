from stinky_api.shadow_paper_decision import build_shadow_paper_decision


def _distribution():
    return {
        "status": "CALIBRATED_EMPIRICAL",
        "pattern_hash": "pat-1",
        "outcome_distribution": {
            "probabilities": {"RUNNER": 0.6, "HELD": 0.2, "FADE": 0.2},
        },
        "market_cap_change_distributions": {
            "1h": {
                "status": "CALIBRATED_EMPIRICAL",
                "probabilities": {
                    "DOWN_GT_50": 0.1,
                    "DOWN_0_TO_50": 0.2,
                    "UP_0_TO_100": 0.4,
                    "UP_GTE_100": 0.3,
                },
            }
        },
        "calibrated_horizons": ["1h"],
        "live_execution": False,
        "trading_authority": False,
        "trade_signal": False,
    }


def _context():
    return {
        "mint": "mint-1",
        "decided_at": "2026-09-09T13:30:00Z",
        "evidence_snapshot": {"feature_complete": True},
        "temporal_cutoff_enforced": True,
        "future_evidence_used": False,
    }


def _policy():
    return {
        "policy_version": "shadow-v1",
        "horizon": "1h",
        "min_runner_probability": 0.5,
        "max_fade_probability": 0.3,
        "min_nonnegative_market_cap_probability": 0.6,
    }


def test_explicit_policy_can_produce_would_enter_without_live_authority():
    result = build_shadow_paper_decision(_distribution(), _context(), _policy())
    assert result["status"] == "SHADOW_DECISION"
    assert result["action"] == "WOULD_ENTER"
    assert result["reason_codes"] == []
    assert result["live_execution"] is False
    assert result["trading_authority"] is False
    assert result["trade_signal"] is False
    assert result["predictive_authority"] is False
    assert result["counterfactual_journal_compatible"] is True


def test_failed_policy_check_produces_would_skip_not_live_trade():
    policy = _policy()
    policy["min_runner_probability"] = 0.8
    result = build_shadow_paper_decision(_distribution(), _context(), policy)
    assert result["action"] == "WOULD_SKIP"
    assert "runner_probability" in result["reason_codes"]
    assert result["live_execution"] is False


def test_missing_threshold_fails_closed_to_unknown():
    policy = _policy()
    del policy["max_fade_probability"]
    result = build_shadow_paper_decision(_distribution(), _context(), policy)
    assert result["status"] == "UNKNOWN"
    assert "max_fade_probability" in result["missing"]


def test_uncalibrated_probability_input_fails_closed():
    distribution = _distribution()
    distribution["status"] = "UNKNOWN"
    result = build_shadow_paper_decision(distribution, _context(), _policy())
    assert result["status"] == "UNKNOWN"
    assert "calibrated_empirical_probability_distribution" in result["missing"]


def test_authoritative_probability_input_is_rejected():
    distribution = _distribution()
    distribution["trading_authority"] = True
    result = build_shadow_paper_decision(distribution, _context(), _policy())
    assert result["status"] == "UNKNOWN"
    assert "non_authoritative_probability_input" in result["missing"]


def test_uncalibrated_policy_horizon_fails_closed():
    policy = _policy()
    policy["horizon"] = "24h"
    result = build_shadow_paper_decision(_distribution(), _context(), policy)
    assert result["status"] == "UNKNOWN"
    assert "policy_horizon_not_calibrated" in result["missing"]


def test_temporally_unsafe_context_fails_closed():
    context = _context()
    context["future_evidence_used"] = True
    result = build_shadow_paper_decision(_distribution(), context, _policy())
    assert result["status"] == "UNKNOWN"
    assert "future_evidence_excluded" in result["missing"]


def test_held_probability_is_preserved_in_snapshot():
    result = build_shadow_paper_decision(_distribution(), _context(), _policy())
    assert result["probability_snapshot"]["held_probability"] == 0.2


def test_evidence_snapshot_is_copied_not_aliased():
    context = _context()
    result = build_shadow_paper_decision(_distribution(), context, _policy())
    context["evidence_snapshot"]["feature_complete"] = False
    assert result["evidence_snapshot"]["feature_complete"] is True
