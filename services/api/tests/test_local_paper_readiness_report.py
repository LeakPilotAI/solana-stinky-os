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
    # Database reads moved from the web proxy to the API pool; preserve the
    # original identity assertions at their actual implementation boundary.
    route=(ROOT/"services/api/src/stinky_api/main.py").read_text(encoding="utf-8")
    panel=(ROOT/"apps/web/src/components/command-center/PaperCalibrationPanel.tsx").read_text(encoding="utf-8")
    assert "policy_cohorts" in route
    assert "LEGACY_UNKNOWN" in route
    assert "policy_evidence_backed" in route
    assert '"historical_identity_inference": False' in route
    cohort_query=next(line for line in route.splitlines() if "LEGACY_UNKNOWN" in line and "paper_runtime_record" in line)
    assert "paper_policy_active" not in cohort_query
    assert "Immutable policy cohorts" in panel
    assert "Historical identity is never inferred from the active policy." in panel


def test_paper_status_preserves_immutable_cohorts_behavior(monkeypatch):
    import asyncio
    from stinky_api.main import paper_status
    from unittest.mock import AsyncMock
    monkeypatch.setattr("stinky_api.paper_status_contract.paper_status_contract", AsyncMock(return_value={}))

    cohort = {"policy_version": "LEGACY_UNKNOWN", "policy_sha256": "UNKNOWN",
              "provenance": "UNKNOWN", "policy_identity": None, "records": 2}
    class Result:
        def mappings(self): return self
        def one(self):
            return {**{key: 0 for key in ("candidates", "runners", "held", "fades",
                "would_watch", "would_skip", "would_enter", "paper_open", "paper_closed",
                "intake_unprocessed", "intake_processed")},
                "producer_version": None, "prospective_started_at": None,
                "represented": 0, "first_candidate_at": None, "latest_candidate_at": None}
        def all(self): return [cohort]
    class Session:
        statements = []
        async def execute(self, statement):
            self.statements.append(str(statement))
            return Result()
    session = Session()
    result = asyncio.run(paper_status(session))
    assert result["status"] == "OBSERVED"
    assert result["policy_cohorts"] == [cohort]
    assert result["historical_identity_inference"] is False
    assert result["aggregate_scope"] == "ALL_IMMUTABLE_POLICY_COHORTS"
    assert "paper_policy_active" not in session.statements[1]
    assert all(statement.lstrip().startswith("SELECT") for statement in session.statements)
    assert result["authority"]["live_execution"] is False
