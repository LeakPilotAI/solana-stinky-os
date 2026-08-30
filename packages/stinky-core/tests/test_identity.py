"""Unique mint + alert_candidate idempotency."""

from __future__ import annotations

from stinky_core.identity import (
    AlertLedger,
    UniqueMintIndex,
    alert_candidate_key,
    canonical_mint,
)
from stinky_core.pools import is_excluded_pool_or_program, is_rankable_wallet


PUMP_MINT = "Hfomz7hrkF6QHc4qWqZz111111111111111111pump"


def test_canonical_mint_strips():
    assert canonical_mint("  " + PUMP_MINT + "  ") == PUMP_MINT
    assert canonical_mint("") is None
    assert canonical_mint(None) is None
    assert canonical_mint("https://axiom.trade/" + PUMP_MINT) is None


def test_unique_mint_same_twice_one_candidate():
    idx = UniqueMintIndex()
    assert idx.add(PUMP_MINT) is True
    assert idx.add(PUMP_MINT) is False
    assert idx.add("  " + PUMP_MINT) is False
    assert len(idx) == 1


def test_duplicate_migration_events_do_not_double_count():
    idx = UniqueMintIndex()
    events = [PUMP_MINT, PUMP_MINT, PUMP_MINT, "OtherMint1111111111111111111111111111"]
    firsts = [idx.add(m) for m in events]
    assert firsts.count(True) == 2
    assert len(idx) == 2


def test_alert_candidate_key_format():
    key = alert_candidate_key(PUMP_MINT)
    assert key == f"alert_candidate:{PUMP_MINT}"


def test_alert_ledger_duplicate_delivery():
    ledger = AlertLedger()
    ok1, k1 = ledger.try_record(PUMP_MINT)
    ok2, k2 = ledger.try_record(PUMP_MINT)
    assert ok1 is True
    assert ok2 is False
    assert k1 == k2 == f"alert_candidate:{PUMP_MINT}"
    assert ledger.delivered == 1
    assert ledger.duplicates == 1
    assert len(ledger) == 1


def test_pool_program_excluded():
    assert is_excluded_pool_or_program("11111111111111111111111111111111")
    assert is_excluded_pool_or_program("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
    assert is_excluded_pool_or_program("pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA")
    assert is_rankable_wallet("11111111111111111111111111111111") is False
    assert is_rankable_wallet(PUMP_MINT) is True


def test_pool_must_not_contaminate_buyers():
    wallets = [
        "11111111111111111111111111111111",
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "HumanWallet1111111111111111111111111111111",
    ]
    rankable = [w for w in wallets if is_rankable_wallet(w)]
    assert rankable == ["HumanWallet1111111111111111111111111111111"]
