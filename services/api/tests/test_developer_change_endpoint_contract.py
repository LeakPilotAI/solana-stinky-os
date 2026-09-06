import pytest

from stinky_api.entity_graph import cross_developer_changes


class Session:
    async def execute(self, statement, params=None):
        class Result:
            def mappings(self): return self
            def all(self): return []
        return Result()


@pytest.mark.asyncio
async def test_developer_change_endpoint_remains_evidence_only_when_empty():
    result = await cross_developer_changes(Session(), limit=25, as_of=None, include_unchanged=False)
    assert result["status"] == "UNKNOWN"
    assert result["items"] == []
    assert result["risk_inferred"] is False
    assert result["quality_inferred"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
    assert result["evidence_only"] is True
