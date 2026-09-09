from stinky_api.adversarial_runner_memory import build_adversarial_runner_memory


def _feature(**overrides):
    row = {
        "mint": "MintA",
        "entity_id": "entity-a",
        "migration_event_id": "migration-a",
        "feature_as_of": "2026-09-09T12:05:00+00:00",
        "feature_complete": True,
        "developer_dual_time_visible": True,
        "correlation_dual_time_visible": True,
        "lifecycle_dual_time_visible": True,
        "lifecycle_evidence_basis": "market_snapshot_observation",
    }
    row.update(overrides)
    return row


def _outcome(**overrides):
    row = {
        "label": "FADE",
        "completed_at": "2026-09-09T12:30:00+00:00",
        "canonical_classification": True,
        "evidence_basis": "completed_market_snapshot_path",
        "source_table": "market_snapshots",
    }
    row.update(overrides)
    return row


def test_later_canonical_fade_becomes_evidence_only_adversarial_case():
    result = build_adversarial_runner_memory(_feature(), _outcome())

    assert result["status"] == "OBSERVED"
    assert result["adversarial_case"] is True
    assert result["outcome"]["label"] == "FADE"
    assert result["temporal_cutoff_enforced"] is True
    assert result["future_evidence_used_in_t0_features"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
    assert result["risk_inferred"] is False
    assert result["intent_inferred"] is False
    assert result["collusion_inferred"] is False


def test_runner_is_observed_but_not_adversarial_case():
    result = build_adversarial_runner_memory(_feature(), _outcome(label="RUNNER"))

    assert result["status"] == "OBSERVED"
    assert result["adversarial_case"] is False
    assert result["adversarial_basis"] is None


def test_incomplete_t0_evidence_stays_unknown():
    result = build_adversarial_runner_memory(
        _feature(feature_complete=False),
        _outcome(),
    )

    assert result["status"] == "UNKNOWN"
    assert "complete_t0_feature_evidence" in result["missing"]
    assert result["predictive_authority"] is False


def test_noncanonical_or_unknown_outcome_stays_unknown():
    result = build_adversarial_runner_memory(
        _feature(),
        _outcome(label="UNKNOWN", canonical_classification=False),
    )

    assert result["status"] == "UNKNOWN"
    assert "canonical_measured_outcome" in result["missing"]
    assert "classified_outcome" in result["missing"]


def test_outcome_must_be_strictly_later_than_frozen_features():
    result = build_adversarial_runner_memory(
        _feature(),
        _outcome(completed_at="2026-09-09T12:05:00+00:00"),
    )

    assert result["status"] == "UNKNOWN"
    assert result["temporal_violation"] is True
    assert result["missing"] == ["strictly_later_outcome_evidence"]
