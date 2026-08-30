from discord_bot.policy import should_alert, category_for_transition


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


def test_severity_upgrade_is_new_alert():
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
