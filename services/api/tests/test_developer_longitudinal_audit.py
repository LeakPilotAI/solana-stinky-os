from datetime import datetime, timezone

import pytest

from stinky_api.developer_longitudinal_audit import (
    describe_developer_change,
    developer_change_feed,
    developer_evidence_hash,
)


def _evidence(*, launches=0, state="NEW-UNKNOWN", wallets=None, funding=None, buyers=None, outcomes=None, missing=None):
    return {
        "entity_id": "11111111-1111-1111-1111-111111111111",
        "reference_mint": "CURRENT",
        "history_state": state,
        "launch_history": {
            "historical_launch_count": launches,
            "outcome_counts": outcomes or {"RUNNER": 0, "HELD": 0, "FADE": 0, "UNKNOWN": launches},
        },
        "associated_wallets": {"records": [{"wallet": w} for w in (wallets or [])]},
        "funding_relationships": {"counterparties": [{"wallet": w, "direction": "INBOUND"} for w in (funding or [])]},
        "recurring_early_buyers": {"status": "OBSERVED", "records": [{"wallet": w} for w in (buyers or [])]},
        "missing": missing or [],
        "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
        "risk_inferred": False,
        "quality_inferred": False,
        "predictive_authority": False,
        "trade_signal": False,
        "evidence_only": True,
    }


def test_hash_is_deterministic_and_descriptive_only():
    a = _evidence(launches=1, state="KNOWN_HISTORY", wallets=["A"])
    b = _evidence(launches=1, state="KNOWN_HISTORY", wallets=["A"])
    assert developer_evidence_hash(a) == developer_evidence_hash(b)


def test_change_describes_new_launch_outcome_wallet_funding_and_buyer_without_judgment():
    previous = _evidence(missing=["prior_developer_launch_history"])
    current = _evidence(
        launches=2,
        state="KNOWN_HISTORY",
        wallets=["DEV", "ASSOC"],
        funding=["FUNDER"],
        buyers=["BUYER"],
        outcomes={"RUNNER": 1, "HELD": 0, "FADE": 0, "UNKNOWN": 1},
    )
    result = describe_developer_change(previous, current)
    kinds = {c["kind"] for c in result["changes"]}
    assert result["status"] == "CHANGED"
    assert "HISTORY_STATE_CHANGED" in kinds
    assert "NEW_LAUNCH_OBSERVED" in kinds
    assert "OUTCOME_COUNTS_CHANGED" in kinds
    assert "ASSOCIATED_WALLET_ADDED" in kinds
    assert "FUNDING_COUNTERPARTY_CHANGED" in kinds
    assert "RECURRING_EARLY_BUYER_CHANGED" in kinds
    assert "UNKNOWN_RESOLVED" in kinds
    assert result["risk_inferred"] is False
    assert result["quality_inferred"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False


class _Mappings:
    def __init__(self, rows): self.rows = rows
    def all(self): return self.rows


class _Result:
    def __init__(self, rows=None): self.rows = rows or []
    def mappings(self): return _Mappings(self.rows)


class _Session:
    def __init__(self, rows): self.rows = rows; self.calls = []
    async def execute(self, statement, params=None):
        sql = str(statement); self.calls.append((sql, params or {}))
        if "WITH ranked AS" in sql: return _Result(self.rows)
        return _Result([])


@pytest.mark.asyncio
async def test_cross_developer_feed_compares_latest_two_visible_snapshots_and_preserves_authority_flags():
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    rows = [{
        "entity_id": "11111111-1111-1111-1111-111111111111",
        "current_evidence": _evidence(launches=1, state="KNOWN_HISTORY", wallets=["DEV"]),
        "previous_evidence": _evidence(),
        "observed_at": now,
        "primary_wallet": "DEV",
        "display_label": "developer",
    }]
    session = _Session(rows)
    result = await developer_change_feed(session, limit=999, as_of=now)
    assert result["status"] == "OBSERVED"
    assert result["bounded"]["limit"] == 200
    assert result["temporal_cutoff_enforced"] is True
    assert result["risk_inferred"] is False
    assert result["quality_inferred"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
    ranked_sql, params = next((sql, p) for sql, p in session.calls if "WITH ranked AS" in sql)
    assert "observed_at <= :as_of" in ranked_sql
    assert "ingested_at <= :as_of" in ranked_sql
    assert params["as_of"] == now
