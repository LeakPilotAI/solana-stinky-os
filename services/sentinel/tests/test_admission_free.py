"""Free-tier admission: pump + dex; fees optional."""

from sentinel.qualify import qualify_fresh_pump_migration, MIN_GLOBAL_FEES_PAID_SOL


def test_floor_constant():
    assert MIN_GLOBAL_FEES_PAID_SOL == 5.0


def test_free_mode_accepts_unknown_fees():
    r = qualify_fresh_pump_migration(
        mint="Abc123pump",
        dex_id="pumpswap",
        global_fees_paid_sol=None,
        require_global_fees=False,
    )
    assert r.accepted is True
    assert r.reason == "ok_fees_unknown"


def test_free_mode_accepts_low_fees():
    r = qualify_fresh_pump_migration(
        mint="Abc123pump",
        dex_id="pumpswap",
        global_fees_paid_sol=0.5,
        require_global_fees=False,
    )
    assert r.accepted is True


def test_strict_mode_rejects_unknown():
    r = qualify_fresh_pump_migration(
        mint="Abc123pump",
        dex_id="pumpswap",
        global_fees_paid_sol=None,
        require_global_fees=True,
    )
    assert r.accepted is False
    assert r.reason == "GLOBAL_FEES_UNKNOWN"


def test_still_rejects_non_pump():
    r = qualify_fresh_pump_migration(
        mint="So11111111111111111111111111111111111111112",
        dex_id="pumpswap",
        global_fees_paid_sol=10.0,
        require_global_fees=False,
    )
    assert r.accepted is False
    assert r.reason == "NOT_PUMP_MINT"


def test_strict_accepts_high_fees():
    r = qualify_fresh_pump_migration(
        mint="Abc123pump",
        dex_id="pumpfun",
        global_fees_paid_sol=6.0,
        require_global_fees=True,
        min_fees_sol=5.0,
    )
    assert r.accepted is True
