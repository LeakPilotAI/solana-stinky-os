from datetime import datetime, timedelta, timezone

from entity_resolver.measured_outcome_classification import classify_completed_market_path


START = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def _track(*, duration=3600):
    return {
        "mint": "MintMeasuredOutcome",
        "migration_at": START,
        "completed_at": START + timedelta(seconds=duration),
    }


def _snapshot(seconds, price, *, volume=1000.0, liquidity=50000.0):
    return {
        "captured_at": START + timedelta(seconds=seconds),
        "price_usd": price,
        "volume_m5_usd": volume,
        "liquidity_usd": liquidity,
    }


def test_complete_measured_path_uses_canonical_runner_contract():
    result = classify_completed_market_path(
        _track(),
        [
            _snapshot(10, 1.0),
            _snapshot(900, 1.4),
            _snapshot(1800, 2.1),
            _snapshot(3590, 1.2),
        ],
    )

    assert result["label"] == "RUNNER"
    assert result["reason"] == "peak_multiple_met"
    assert result["label_version"] == "outcome-v1.1.0"
    assert result["peak_multiple"] == 2.1
    assert result["valid_price_snapshot_count"] == 4
    assert result["canonical_classification"] is True
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False


def test_complete_measured_path_can_be_held_without_becoming_runner():
    result = classify_completed_market_path(
        _track(),
        [
            _snapshot(10, 1.0),
            _snapshot(1200, 1.25),
            _snapshot(2400, 1.10),
            _snapshot(3590, 1.05),
        ],
    )

    assert result["label"] == "HELD"
    assert result["reason"] == "held_within_drawdown"
    assert result["peak_multiple"] == 1.25
    assert 0.15 < result["drawdown"] < 0.17


def test_complete_measured_path_can_be_fade_from_measured_drawdown():
    result = classify_completed_market_path(
        _track(),
        [
            _snapshot(10, 1.0),
            _snapshot(900, 1.4),
            _snapshot(1800, 0.65),
            _snapshot(3590, 0.60),
        ],
    )

    assert result["label"] == "FADE"
    assert result["reason"] == "drawdown_fade"
    assert result["peak_multiple"] == 1.4
    assert result["drawdown"] > 0.5


def test_short_track_remains_unknown_even_with_large_price_move():
    result = classify_completed_market_path(
        _track(duration=1800),
        [_snapshot(10, 1.0), _snapshot(1700, 3.0)],
    )

    assert result["label"] == "UNKNOWN"
    assert result["reason"] == "incomplete_observation_window"


def test_missing_price_path_remains_unknown():
    result = classify_completed_market_path(
        _track(),
        [
            {"captured_at": START + timedelta(seconds=10), "price_usd": None},
            {"captured_at": START + timedelta(seconds=3590), "price_usd": None},
        ],
    )

    assert result["label"] == "UNKNOWN"
    assert result["reason"] == "insufficient_measured_price_path"
