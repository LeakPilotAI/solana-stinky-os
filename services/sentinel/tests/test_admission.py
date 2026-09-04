"""Unit tests for canonical admission (no network)."""

from sentinel.admission import evaluate_pump_quality, evaluate_alert_payload
from sentinel.qualify import MIN_GLOBAL_FEES_PAID_SOL


def test_min_floor_is_five():
    assert MIN_GLOBAL_FEES_PAID_SOL == 5.0


def test_reject_unknown_fees():
    d = evaluate_pump_quality(
        mint="Abc123pump",
        dex_id="pumpswap",
        fees_sol=None,
    )
    assert d.accepted is False
    assert d.reason == "GLOBAL_FEES_UNKNOWN"


def test_reject_low_fees():
    d = evaluate_pump_quality(
        mint="Abc123pump",
        dex_id="pumpswap",
        fees_sol=1.2,
        min_fees_sol=5.0,
    )
    assert d.accepted is False
    assert d.reason.startswith("LOW_GLOBAL_FEES")


def test_accept_fees_ok():
    d = evaluate_pump_quality(
        mint="Abc123pump",
        dex_id="pumpswap",
        fees_sol=5.01,
        min_fees_sol=5.0,
    )
    assert d.accepted is True
    assert d.reason == "ok"


def test_reject_non_pump():
    d = evaluate_pump_quality(
        mint="So11111111111111111111111111111111111111112",
        dex_id="pumpswap",
        fees_sol=10.0,
    )
    assert d.accepted is False
    assert d.reason == "NOT_PUMP_MINT"


def test_alert_payload_unknown():
    d = evaluate_alert_payload({"mint": "Xpump", "dex_id": "pumpfun"})
    assert d.accepted is False
    assert d.reason == "GLOBAL_FEES_UNKNOWN"
