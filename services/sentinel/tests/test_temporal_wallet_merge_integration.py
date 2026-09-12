from sentinel.reevaluation import normalize_wallet_performance_row
from sentinel.temporal_wallet_merge import _FieldMergeMemory
from stinky_core.intelligence import analyze_wallets


class FakeMemory:
    def wallet_performance_as_of(self, wallet_ids, *, as_of, exclude_mint=None):
        return {
            "wallet-a-111111111111111111111111111111": {
                "early_buy_count": 10,
                "tokens_purchased": 15,
                "hit_rate": None,
            }
        }


def test_normalized_sql_history_survives_memory_merge_and_becomes_known_wallet_intel():
    wallet = "wallet-a-111111111111111111111111111111"
    normalized = normalize_wallet_performance_row(
        {
            "wallet": wallet,
            "early_buy_count": 10,
            "tokens_purchased": 15,
            "hit_rate": None,
            "early_success_sample": 13,
            "early_success_rate": 1.0,
            "early_on_runner": 13,
        }
    )
    proxy = _FieldMergeMemory(FakeMemory(), {wallet: normalized})
    perf = proxy.wallet_performance_as_of(
        [wallet], as_of="2026-09-12T12:30:00Z", exclude_mint="current-mint"
    )
    intel = analyze_wallets(
        [{"wallet": wallet, "rank": 1, "sol_spent": 0.2}],
        perf,
    )
    assert intel.status == "KNOWN"
    assert intel.smart_wallet_count == 1
    assert intel.avg_hit_rate == 1.0
