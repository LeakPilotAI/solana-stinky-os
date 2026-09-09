from pathlib import Path


def test_service_uses_diagnostic_funding_scan():
    source = Path("services/entity-resolver/src/entity_resolver/service.py").read_text(encoding="utf-8")
    assert "scan_recent_inbound_transfers" in source
    assert "entity.wallet_funding_scan_completed" in source
