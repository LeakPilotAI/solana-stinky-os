from datetime import datetime, timedelta, timezone

from entity_resolver.behavior import build_behavioral_fingerprint, cadence_bucket


def test_cadence_bucket_boundaries() -> None:
    assert cadence_bucket(None) == "unknown"
    assert cadence_bucket(3600) == "high_frequency"
    assert cadence_bucket(3601) == "active"
    assert cadence_bucket(86400) == "active"
    assert cadence_bucket(86401) == "recurring"
    assert cadence_bucket(604800) == "recurring"
    assert cadence_bucket(604801) == "sparse"


def test_behavioral_fingerprint_is_descriptive_and_preserves_unknown_outcomes() -> None:
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    launches = [
        {"observed_at": start, "outcome_status": "completed"},
        {"observed_at": start + timedelta(hours=2), "outcome_status": None},
        {"observed_at": start + timedelta(hours=6), "outcome_status": "completed"},
    ]

    result = build_behavioral_fingerprint(launches)

    assert result["launch_count"] == 3
    assert result["outcomes_known"] == 2
    assert result["completed_count"] == 2
    assert result["outcomes_unknown"] == 1
    assert result["outcome_coverage"] == 2 / 3
    assert result["first_launch_at"] == start.isoformat()
    assert result["last_launch_at"] == (start + timedelta(hours=6)).isoformat()
    assert result["median_launch_interval_sec"] == 10800.0
    assert result["cadence_bucket"] == "active"
    assert result["evidence_basis"] == "entity_launches+entity_wallets+early_buyer_observations"
    assert result["early_buyer_wallet_count"] is None
    assert result["early_buyer_mint_count"] is None
    assert result["repeat_early_buyer_wallet_count"] is None


def test_wallet_behavior_is_descriptive() -> None:
    result = build_behavioral_fingerprint(
        [],
        wallets=[
            {"wallet": "primary", "role": "primary"},
            {"wallet": "buyer1", "role": "early_buyer"},
            {"wallet": "buyer2", "role": "early_buyer"},
        ],
        early_buy_stats={
            "early_buyer_wallet_count": 2,
            "early_buyer_mint_count": 5,
            "repeat_early_buyer_wallet_count": 1,
            "evidence_basis": "migration_buyers",
        },
    )

    assert result["wallet_count"] == 3
    assert result["wallet_role_counts"] == {"early_buyer": 2, "primary": 1}
    assert result["early_buyer_wallet_count"] == 2
    assert result["early_buyer_mint_count"] == 5
    assert result["repeat_early_buyer_wallet_count"] == 1
    assert result["early_buyer_evidence"] == "migration_buyers"


def test_empty_history_is_unknown_not_negative() -> None:
    result = build_behavioral_fingerprint([])

    assert result["launch_count"] == 0
    assert result["outcomes_known"] == 0
    assert result["completed_count"] == 0
    assert result["outcomes_unknown"] == 0
    assert result["outcome_coverage"] is None
    assert result["cadence_bucket"] == "unknown"
    assert result["wallet_count"] == 0
    assert result["early_buyer_wallet_count"] is None
    assert result["early_buyer_mint_count"] is None
    assert result["repeat_early_buyer_wallet_count"] is None
