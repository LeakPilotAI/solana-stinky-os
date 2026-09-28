from datetime import datetime, timezone

import pytest

from stinky_api.market_pattern_history import market_pattern_history, persist_market_pattern_occurrence
from stinky_api.market_path_patterns import canonical_pattern_hash


class Result:
    def __init__(self, *, first_value=None, rows=None):
        self._first_value = first_value
        self._rows = rows or []

    def first(self):
        return self._first_value

    def mappings(self):
        return self

    def all(self):
        return self._rows


@pytest.mark.asyncio
async def test_persist_pattern_occurrence_is_idempotent_contract():
    class Session:
        def __init__(self):
            self.calls = []
            self.committed = False
            self.rolled_back = False

        async def execute(self, statement, params=None):
            sql = str(statement)
            self.calls.append((sql, params or {}))
            if "INSERT INTO market_path_pattern_occurrences" in sql:
                return Result(first_value=(1,))
            return Result()

        async def commit(self):
            self.committed = True

        async def rollback(self):
            self.rolled_back = True

    session = Session()
    signature = {"observed_horizons": ["5m"], "observed_record_count": 1, "metrics": {}}
    observed_at = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)

    pattern_hash = await persist_market_pattern_occurrence(
        session,
        mint="MINT",
        signature=signature,
        observed_at=observed_at,
    )

    assert pattern_hash == canonical_pattern_hash(signature)
    assert session.committed is True
    assert session.rolled_back is False
    assert any("ON CONFLICT DO NOTHING" in sql for sql, _ in session.calls)
    assert any("occurrence_count = occurrence_count + 1" in sql for sql, _ in session.calls)


@pytest.mark.asyncio
async def test_history_derives_cutoff_safe_coverage_from_occurrences():
    class Session:
        async def execute(self, statement, params=None):
            assert "observed_at <= :as_of" in str(statement)
            assert params["limit"] == 2
            return Result(rows=[
                {
                    "mint": "A",
                    "observed_at": datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc),
                    "ingested_at": datetime(2026, 9, 5, 10, 1, tzinfo=timezone.utc),
                    "source": "test",
                    "evidence_basis": "observed_market_lifecycle_analysis",
                    "signature": {"x": 1},
                    "created_at": datetime(2026, 9, 5, 10, 1, tzinfo=timezone.utc),
                },
                {
                    "mint": "B",
                    "observed_at": datetime(2026, 9, 5, 11, 0, tzinfo=timezone.utc),
                    "ingested_at": datetime(2026, 9, 5, 11, 1, tzinfo=timezone.utc),
                    "source": "test",
                    "evidence_basis": "observed_market_lifecycle_analysis",
                    "signature": {"x": 1},
                    "created_at": datetime(2026, 9, 5, 11, 1, tzinfo=timezone.utc),
                },
            ])

    result = await market_pattern_history(
        Session(),
        "abc123",
        limit=2,
        as_of="2026-09-05T11:30:00Z",
    )

    assert result["status"] == "OBSERVED"
    assert result["occurrence_count"] == 2
    assert result["distinct_market_count"] == 2
    assert result["first_observed_at"] == "2026-09-05T10:00:00+00:00"
    assert result["last_observed_at"] == "2026-09-05T11:00:00+00:00"
    assert result["temporal_cutoff_enforced"] is True
    assert result["evidence_only"] is True


@pytest.mark.asyncio
async def test_invalid_cutoff_fails_closed():
    result = await market_pattern_history(object(), "abc123", as_of="not-a-time")
    assert result["status"] == "UNKNOWN"
    assert result["missing"] == ["invalid_as_of"]


def test_market_pattern_signature_stabilizes_insignificant_float_noise():
    from stinky_api.market_outcome_analysis import market_path_signature
    from stinky_api.market_path_patterns import canonical_pattern_hash

    base = {
        "status": "OBSERVED",
        "observed_horizons": ["5m", "15m"],
        "observed_record_count": 2,
        "metrics": {
            "price_usd": {
                "observations": 2,
                "first": {"horizon": "5m"},
                "last": {"horizon": "15m"},
                "percent_change_first_to_last": 12.3456781,
            }
        },
    }
    noisy = {
        **base,
        "metrics": {
            "price_usd": {
                **base["metrics"]["price_usd"],
                "percent_change_first_to_last": 12.3456782,
            }
        },
    }

    a = market_path_signature(base)["signature"]
    b = market_path_signature(noisy)["signature"]
    assert a == b
    assert canonical_pattern_hash(a) == canonical_pattern_hash(b)
    assert a["metrics"]["price_usd"]["percent_change_first_to_last"] == 12.3457
