from datetime import datetime, timezone

from stinky_api.pattern_discovery_dataset import _resolve_label


def test_measured_runner_and_fade_are_usable_labels() -> None:
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    runner, runner_basis, runner_provenance = _resolve_label(
        None,
        {"label": "runner", "evaluated_at": ts, "snapshots_n": 4},
    )
    fade, fade_basis, _ = _resolve_label(
        None,
        {"label": "fade", "evaluated_at": ts, "snapshots_n": 5},
    )
    assert runner == "RUNNER"
    assert runner_basis == "measured_token_outcomes_safe_mapping"
    assert runner_provenance["source_event"] == "token_outcomes"
    assert fade == "FADE"
    assert fade_basis == "measured_token_outcomes_safe_mapping"


def test_legacy_mid_never_becomes_held() -> None:
    label, basis, provenance = _resolve_label(None, {"label": "mid", "evaluated_at": None})
    assert label == "UNKNOWN"
    assert basis == "token_outcome_not_semantically_canonical"
    assert provenance["legacy_label"] == "mid"


def test_completion_event_without_outcome_remains_unknown_even_when_completed() -> None:
    event = {
        "event_type": "post_migration.tracking_completed",
        "event_id": "evt",
        "payload": {"mint": "mint-a", "trades_seen": 12, "duration_sec": 1800},
    }
    label, basis, _ = _resolve_label(event, None)
    assert label == "UNKNOWN"
    assert basis == "tracking_completed_has_no_canonical_outcome"
