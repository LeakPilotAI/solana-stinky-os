from discord_bot.policy import should_alert, category_for_transition, format_quality_alert
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[3] / "packages" / "stinky-core" / "src"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from stinky_core.operator import classify_delivery, would_policy_fire


def test_same_state_is_silent():
    spec = should_alert(
        mint="MintA",
        previous_state="DETERIORATING",
        current_state="DETERIORATING",
        now=1_000.0,
    )
    assert spec is None
    assert category_for_transition("WATCH", "WATCH") is None


def test_deteriorating_is_warning():
    spec = should_alert(
        mint="MintA",
        previous_state="STABLE",
        current_state="DETERIORATING",
        now=1_000.0,
    )
    assert spec is not None
    assert spec["category"] == "WARNING"
    assert spec["not_a_buy"] is True
    assert spec["calibrated_probability"] is False


def test_severe_is_critical_and_cooldown_blocks_repeat():
    first = should_alert(
        mint="MintA",
        previous_state="DETERIORATING",
        current_state="SEVERE_DETERIORATION",
        now=1_000.0,
    )
    assert first is not None
    assert first["category"] == "CRITICAL"
    blocked = should_alert(
        mint="MintA",
        previous_state="DETERIORATING",
        current_state="SEVERE_DETERIORATION",
        last_alert_at=1_000.0,
        last_category="CRITICAL",
        now=1_100.0,
    )
    assert blocked is None


def test_unknown_does_not_alert():
    spec = should_alert(mint="MintA", previous_state="STABLE", current_state="UNKNOWN", now=1.0)
    assert spec is None


def test_resolve_from_dip():
    spec = should_alert(mint="MintA", previous_state="WATCH", current_state="HEALTHY", now=1.0)
    assert spec is not None
    assert spec["category"] == "RESOLVED"


def test_severity_upgrade_bypasses_same_category_only():
    spec = should_alert(
        mint="MintA",
        previous_state="WATCH",
        current_state="DETERIORATING",
        last_alert_at=1_000.0,
        last_category="WATCH",
        now=1_010.0,
    )
    assert spec is not None
    assert spec["category"] == "WARNING"


def test_format_quality_alert_is_not_a_trade():
    spec = should_alert(
        mint="MintA",
        previous_state="STABLE",
        current_state="DETERIORATING",
        now=1.0,
    )
    assert spec is not None
    text = format_quality_alert(
        spec,
        why=[{"explanation": "liquidity down ≥ 70% vs Gate 1"}],
        evidence_quality="GOOD",
        timestamp="2026-01-01T00:05:00+00:00",
        unknown=["unique_buyers"],
    )
    assert "MintA" in text
    assert "STABLE" in text and "DETERIORATING" in text
    assert "liquidity down" in text
    assert "GOOD" in text
    assert "unique_buyers" in text
    assert "Not a buy" in text
    assert "Not a sell" in text
    assert spec["not_a_buy"] is True
    assert spec["not_a_sell"] is True


def test_policy_fired_is_not_delivery():
    assert would_policy_fire("HEALTHY", "DETERIORATING") is True
    assert classify_delivery(attempted=False, sent=0, failed=0) == "NOT ATTEMPTED"
    assert classify_delivery(attempted=True, sent=1, failed=0) == "SENT"
    assert classify_delivery(attempted=True, sent=0, failed=1) == "FAILED"
    assert classify_delivery(attempted=None) == "UNKNOWN"
