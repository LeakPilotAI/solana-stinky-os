import pytest

from stinky_api import investigation_entity_network
from stinky_api.entity_graph import investigation_calibration_evidence


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _Session:
    def __init__(self):
        self.calls = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return _Result(("creator-wallet",))


@pytest.mark.asyncio
async def test_calibration_endpoint_resolves_creator_and_returns_compact_synthesis(monkeypatch):
    captured = {}

    async def fake_network(session, **kwargs):
        captured.update(kwargs)
        return {
            "market_pattern_calibration_synthesis": {
                "status": "OBSERVED",
                "pattern_hash": "p1",
                "evidence_status": "PARTIAL_EVIDENCE",
                "current_calibration_state": "STABLE",
                "predictive_authority": False,
                "trade_signal": False,
                "evidence_only": True,
            }
        }

    monkeypatch.setattr(investigation_entity_network, "entity_network_for_investigation", fake_network)
    session = _Session()
    result = await investigation_calibration_evidence("mint-1", session)

    assert captured["creator_wallet"] == "creator-wallet"
    assert captured["mint"] == "mint-1"
    assert captured["wallet_limit"] == 100
    assert captured["relationship_limit"] == 500
    assert result["mint"] == "mint-1"
    assert result["calibration"]["evidence_status"] == "PARTIAL_EVIDENCE"
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
    assert result["evidence_only"] is True


@pytest.mark.asyncio
async def test_calibration_endpoint_preserves_unknown_synthesis(monkeypatch):
    async def fake_network(session, **kwargs):
        return {}

    monkeypatch.setattr(investigation_entity_network, "entity_network_for_investigation", fake_network)
    result = await investigation_calibration_evidence("mint-2", _Session())

    assert result["status"] == "UNKNOWN"
    assert result["calibration"]["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["calibration"]["predictive_authority"] is False
    assert result["calibration"]["trade_signal"] is False
