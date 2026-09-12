from sentinel.temporal_wallet_merge import _FieldMergeMemory, TemporalWalletMergeVolumeMonitor


class FakeMemory:
    def __init__(self, rows):
        self.rows = rows
        self.marker = "base-memory"

    def wallet_performance_as_of(self, wallet_ids, *, as_of, exclude_mint=None):
        return {w: dict(self.rows[w]) for w in wallet_ids if w in self.rows}


def test_field_merge_fills_missing_history_without_overwriting_memory():
    base = FakeMemory(
        {
            "wallet-a": {
                "early_buy_count": 8,
                "tokens_purchased": 9,
                "hit_rate": None,
                "source": "memory",
            }
        }
    )
    overlay = {
        "wallet-a": {
            "early_buy_count": 99,
            "tokens_purchased": 99,
            "hit_rate": 0.75,
            "sample_resolved": 12,
            "runners": 9,
            "source": "sql",
        }
    }
    proxy = _FieldMergeMemory(base, overlay)
    row = proxy.wallet_performance_as_of(
        ["wallet-a"], as_of="2026-09-12T12:30:00Z", exclude_mint="mint-a"
    )["wallet-a"]

    assert row["early_buy_count"] == 8
    assert row["tokens_purchased"] == 9
    assert row["source"] == "memory"
    assert row["hit_rate"] == 0.75
    assert row["sample_resolved"] == 12
    assert row["runners"] == 9
    assert proxy.marker == "base-memory"


def test_field_merge_adds_wallet_missing_from_memory():
    proxy = _FieldMergeMemory(
        FakeMemory({}),
        {"wallet-a": {"early_buy_count": 4, "tokens_purchased": 5, "sample_resolved": 3}},
    )
    rows = proxy.wallet_performance_as_of(
        ["wallet-a"], as_of="2026-09-12T12:30:00Z", exclude_mint="mint-a"
    )
    assert rows["wallet-a"]["sample_resolved"] == 3


def test_monitor_is_still_normal_reevaluator_with_scoped_overlay():
    assert issubclass(TemporalWalletMergeVolumeMonitor, __import__(
        "sentinel.reevaluation", fromlist=["ReevaluatingVolumeMonitor"]
    ).ReevaluatingVolumeMonitor)
    source = __import__("inspect").getsource(
        TemporalWalletMergeVolumeMonitor._reevaluate_with_complete_wallet_history
    )
    assert "finally" in source
    assert "self._memory = base" in source
