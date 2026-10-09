from dataclasses import asdict
from datetime import datetime, timezone, timedelta
import pytest
from stinky_core.memory import IntelligenceMemory

T = datetime(2026, 10, 9, tzinfo=timezone.utc)
W = '11111111111111111111111111111112'

@pytest.mark.parametrize('kind', ['wallet', 'market'])
def test_bulk_hydration_preserves_first_record_validation_and_order(kind):
    memory = IntelligenceMemory()
    if kind == 'wallet':
        rows = [dict(wallet=W, mint='mint', observed_at=T, source='first', role='early_buyer'),
                dict(wallet=W, mint='mint', observed_at=T+timedelta(seconds=1), source='duplicate'),
                dict(wallet=W, mint='mint', observed_at=T, role='seller', source='different-role'),
                dict(wallet='', mint='bad', observed_at=T),
                dict(wallet=W, mint='bad', observed_at='invalid')]
        assert memory.load_wallet_obs(iter(rows)) == 2
        assert [o.source for o in memory.wallet_obs] == ['first', 'different-role']
        assert memory.load_wallet_obs(rows) == 0
        assert memory.wallet_obs[0].observed_at == T
    else:
        rows = [dict(mint='mint', observed_at=T, price_usd=1, buys=3, sells=1),
                dict(mint='mint', observed_at=T.isoformat(), price_usd=999),
                dict(mint='mint', observed_at=T+timedelta(seconds=1), price_usd=None),
                dict(mint='', observed_at=T), dict(mint='bad', observed_at='invalid')]
        assert memory.load_market_ticks(iter(rows)) == 2
        assert memory.market_ticks[0].price_usd == 1
        assert memory.market_ticks[0].buy_sell_ratio == .75
        assert memory.market_ticks[1].price_usd is None
        assert memory.load_market_ticks(rows) == 0

@pytest.mark.parametrize('kind', ['wallet', 'market'])
def test_preexisting_and_externally_appended_records_remain_authoritative(kind):
    m = IntelligenceMemory()
    if kind == 'wallet':
        row = dict(wallet=W, mint='mint', observed_at=T)
        assert m.record_wallet(**row)
        before = [asdict(x) for x in m.wallet_obs]
        assert m.load_wallet_obs([row]) == 0
        assert [asdict(x) for x in m.wallet_obs] == before
        m.wallet_obs.clear()
        assert m.load_wallet_obs([row]) == 1
    else:
        row = dict(mint='mint', observed_at=T, liquidity_usd=12)
        assert m.record_market_tick(**row)
        before = [asdict(x) for x in m.market_ticks]
        assert m.load_market_ticks([row]) == 0
        assert [asdict(x) for x in m.market_ticks] == before
        m.market_ticks.clear()
        assert m.load_market_ticks([row]) == 1

class CountedList(list):
    def __init__(self, values):
        super().__init__(values)
        self.visits = 0
    def __iter__(self):
        for value in super().__iter__():
            self.visits += 1
            yield value

@pytest.mark.parametrize('kind', ['wallet', 'market'])
def test_bulk_loading_scans_prior_evidence_once_without_timing_assertions(kind):
    m = IntelligenceMemory()
    if kind == 'wallet':
        load = m.load_wallet_obs
        rows = [dict(wallet=W, mint=str(i), observed_at=T) for i in range(2000)]
        load(rows[:1000])
        m.wallet_obs = CountedList(m.wallet_obs)
        evidence = m.wallet_obs
    else:
        load = m.load_market_ticks
        rows = [dict(mint=str(i), observed_at=T) for i in range(2000)]
        load(rows[:1000])
        m.market_ticks = CountedList(m.market_ticks)
        evidence = m.market_ticks
    assert load(rows) == 1000
    assert evidence.visits == 1000
    assert len(evidence) == 2000
