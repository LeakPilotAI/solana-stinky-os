from pathlib import Path

from scripts.report_paper_policy_readiness import summarize

ROOT = Path(__file__).resolve().parents[3]


def test_report_calculates_exact_deficits_and_remains_read_only():
    raw = {
        "status": "UNKNOWN",
        "prospective_closed_outcomes": 12,
        "prospective_outcome_counts": {"RUNNER": 7, "HELD": 5, "FADE": 0},
        "missing": ["sufficient_closed_outcomes"],
        "prospective_started_at": "2026-09-10T06:00:00+00:00",
    }
    report = summarize(raw, min_closed=50, min_market=40, min_classes=3)
    assert report["deficits"] == {
        "closed_outcomes_needed": 38,
        "outcome_classes_needed": 1,
        "market_cap_samples_needed": 40,
    }
    assert report["observed"]["outcome_counts"] == {"RUNNER": 7, "HELD": 5, "FADE": 0}
    assert report["threshold_proposal"] is None
    assert report["read_only_report"] is True
    assert report["automatic_activation"] is False
    assert report["live_execution"] is False
    assert report["trading_authority"] is False


def test_ready_report_surfaces_proposal_without_activating_it():
    raw = {
        "status": "READY_FOR_OPERATOR_REVIEW",
        "prospective_closed_outcomes": 60,
        "prospective_outcome_counts": {"RUNNER": 30, "HELD": 20, "FADE": 10},
        "evidence": {"market_cap_samples": 60},
        "threshold_proposal": {
            "horizon": "1h",
            "min_runner_probability": 0.3,
            "max_fade_probability": 0.3,
            "min_nonnegative_market_cap_probability": 0.4,
        },
        "point_estimates": {"runner_probability": 0.5},
        "missing": [],
    }
    report = summarize(raw, min_closed=50, min_market=50, min_classes=3)
    assert report["status"] == "READY_FOR_OPERATOR_REVIEW"
    assert report["deficits"] == {
        "closed_outcomes_needed": 0,
        "outcome_classes_needed": 0,
        "market_cap_samples_needed": 0,
    }
    assert report["threshold_proposal"]["horizon"] == "1h"
    assert report["automatic_activation"] is False


def test_cli_requires_explicit_criteria_and_contains_no_policy_writes():
    source = (ROOT / "scripts/report_paper_policy_readiness.py").read_text(encoding="utf-8")
    for option in ("--min-closed-outcomes", "--min-market-cap-samples", "--min-outcome-classes"):
        line = next(line for line in source.splitlines() if f'add_argument("{option}"' in line)
        assert "required=True" in line
        assert "default=" not in line
    lowered = source.lower()
    forbidden = (
        "provision_paper_policy",
        "paper_policy_active",
        "insert into paper_policy_registry",
        "update paper_policy_active",
        "send_transaction",
        "sign_transaction",
        "private_key",
        "solana.rpc",
    )
    assert not any(token in lowered for token in forbidden)


def test_command_center_groups_runtime_by_frozen_policy_identity_without_backfill():
    route=(ROOT/"apps/web/src/app/api/paper-status/route.ts").read_text(encoding="utf-8")
    panel=(ROOT/"apps/web/src/components/command-center/PaperCalibrationPanel.tsx").read_text(encoding="utf-8")
    assert "policy_cohorts" in route
    assert "LEGACY_UNKNOWN" in route
    assert "policy_evidence_backed" in route
    assert 'historical_identity_inference: false' in route
    cohort_query=next(line for line in route.splitlines() if "LEGACY_UNKNOWN" in line and "paper_runtime_record" in line)
    assert "paper_policy_active" not in cohort_query
    assert "Immutable policy cohorts" in panel
    assert "Historical identity is never inferred from the active policy." in panel
