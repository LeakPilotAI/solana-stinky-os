from stinky_api.counterfactual_journal import build_counterfactual_journal_entry


def _decision(**overrides):
    row = {
        "mint": "MintA",
        "decided_at": "2026-09-09T13:00:00+00:00",
        "action": "WOULD_ENTER",
        "evidence_snapshot": {"fees_sol": 4.2, "volume_m5_usd": 120000},
        "reason_codes": ["paper_gate_observed"],
        "policy_version": "shadow-v1",
        "temporal_cutoff_enforced": True,
        "future_evidence_used": False,
    }
    row.update(overrides)
    return row


def _outcome(**overrides):
    row = {
        "label": "RUNNER",
        "completed_at": "2026-09-09T13:30:00+00:00",
        "canonical_classification": True,
        "evidence_basis": "completed_market_snapshot_path",
        "source_table": "market_snapshots",
    }
    row.update(overrides)
    return row


def test_open_entry_freezes_t0_paper_decision_without_live_authority():
    decision = _decision()
    result = build_counterfactual_journal_entry(decision)
    decision["evidence_snapshot"]["fees_sol"] = 999

    assert result["status"] == "OPEN"
    assert result["decision"]["action"] == "WOULD_ENTER"
    assert result["decision"]["evidence_snapshot"]["fees_sol"] == 4.2
    assert result["outcome"] is None
    assert result["live_execution"] is False
    assert result["trading_authority"] is False
    assert result["paper_only"] is True


def test_later_canonical_outcome_attaches_without_rewriting_t0_decision():
    result = build_counterfactual_journal_entry(_decision(), _outcome(label="FADE"))

    assert result["status"] == "OBSERVED"
    assert result["decision"]["action"] == "WOULD_ENTER"
    assert result["outcome"]["label"] == "FADE"
    assert result["outcome_attached_after_decision"] is True
    assert result["t0_decision_rewritten_by_outcome"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False


def test_incomplete_or_temporally_unsafe_t0_decision_fails_closed():
    result = build_counterfactual_journal_entry(
        _decision(evidence_snapshot={}, future_evidence_used=True)
    )

    assert result["status"] == "UNKNOWN"
    assert "frozen_t0_evidence_snapshot" in result["missing"]
    assert "future_evidence_excluded" in result["missing"]
    assert result["trading_authority"] is False


def test_unknown_or_noncanonical_outcome_does_not_close_entry():
    result = build_counterfactual_journal_entry(
        _decision(),
        _outcome(label="UNKNOWN", canonical_classification=False),
    )

    assert result["status"] == "UNKNOWN"
    assert "canonical_measured_outcome" in result["missing"]
    assert "classified_outcome" in result["missing"]
    assert result["decision"]["action"] == "WOULD_ENTER"


def test_outcome_must_be_strictly_later_than_decision():
    result = build_counterfactual_journal_entry(
        _decision(),
        _outcome(completed_at="2026-09-09T13:00:00+00:00"),
    )

    assert result["status"] == "UNKNOWN"
    assert result["temporal_violation"] is True
    assert result["missing"] == ["strictly_later_outcome_evidence"]


def test_held_is_preserved_as_measured_outcome_not_forced_to_runner_or_fade():
    result = build_counterfactual_journal_entry(_decision(action="WOULD_WATCH"), _outcome(label="HELD"))

    assert result["status"] == "OBSERVED"
    assert result["decision"]["action"] == "WOULD_WATCH"
    assert result["outcome"]["label"] == "HELD"
