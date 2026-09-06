from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PROVENANCE = ROOT / "services" / "api" / "src" / "stinky_api" / "phase10_cohort_provenance.py"
DATASET = ROOT / "services" / "api" / "src" / "stinky_api" / "pattern_discovery_dataset.py"
SCRIPT = ROOT / "scripts" / "audit-phase10-cohort-provenance.py"


def test_exact_cohort_matches_dataset_ordering_and_cutoffs() -> None:
    provenance = PROVENANCE.read_text(encoding="utf-8")
    dataset = DATASET.read_text(encoding="utf-8")
    for fragment in (
        "l.observed_at + make_interval(secs => :feature_seconds) <= :dataset_as_of",
        "l.created_at <= :dataset_as_of",
        "ORDER BY l.observed_at DESC, l.id DESC",
        "LIMIT :limit",
    ):
        assert fragment in provenance
        assert fragment in dataset


def test_feature_evidence_remains_dual_time_fail_closed() -> None:
    provenance = PROVENANCE.read_text(encoding="utf-8")
    dataset = DATASET.read_text(encoding="utf-8")
    assert "s.observed_at <= c.feature_as_of" in provenance
    assert "s.ingested_at <= c.feature_as_of" in provenance
    assert "o.observed_at <= c.feature_as_of" in provenance
    assert "o.ingested_at <= c.feature_as_of" in provenance
    assert "s.ingested_at <= l.observed_at + make_interval" in dataset
    assert "o.ingested_at <= l.observed_at + make_interval" in dataset


def test_market_snapshots_are_diagnostic_not_historical_feature_authority() -> None:
    source = PROVENANCE.read_text(encoding="utf-8")
    assert '"market_snapshots_have_no_independent_ingested_at": True' in source
    assert '"market_snapshots_not_promoted_to_dual_time_features": True' in source
    assert '"market_snapshot_is_dual_time_feature_authority": False' in source


def test_dataset_does_not_convert_completion_to_outcome_or_mid_to_held() -> None:
    source = DATASET.read_text(encoding="utf-8")
    assert '"tracking_completed_without_explicit_outcome_is_not_a_label": True' in source
    assert '"legacy_mid_is_not_mapped_to_held": True' in source
    assert "canonical_token_outcome_label" in source
    assert "evaluated_at <= :dataset_as_of" in source


def test_operator_audit_is_read_only_and_not_command_center_coupled() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    provenance = PROVENANCE.read_text(encoding="utf-8")
    assert "audit_phase10_cohort_provenance" in script
    assert "commit(" not in script
    assert "INSERT INTO" not in provenance
    assert "UPDATE " not in provenance
    assert "DELETE FROM" not in provenance
    assert "command_center" not in provenance.lower()
