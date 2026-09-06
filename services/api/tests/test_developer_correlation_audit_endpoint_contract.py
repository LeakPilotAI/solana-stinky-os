import inspect

from stinky_api import entity_graph


def test_correlation_audit_routes_are_exposed():
    source = inspect.getsource(entity_graph)
    assert '@router.get("/developer-correlation-changes")' in source
    assert '@router.get("/developer-correlation/{entity_id}/history")' in source
    assert "persist_developer_correlation_snapshot" in source
    assert "developer_correlation_audit_history" in source


def test_per_mint_contract_exposes_correlation_audit_without_authority():
    source = inspect.getsource(entity_graph.investigation_calibration_evidence)
    assert '"developer_correlation_audit"' in source
    assert '"developer_correlation_latest_change"' in source
    assert '"ownership_inferred": False' in source
    assert '"coordination_inferred": False' in source
    assert '"predictive_authority": False' in source
    assert '"trade_signal": False' in source
