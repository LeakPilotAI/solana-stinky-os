from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from entity_resolver.service import EntityService


async def test_observe_wallet_funding_persists_direct_inbound_transfer_once() -> None:
    service = EntityService.__new__(EntityService)
    service._funding_scanned_wallets = set()
    service._http = object()
    service._relationships = type("Relationships", (), {})()
    service._relationships.record_funding_observation = AsyncMock()

    transfer = {
        "source_wallet": "SOURCE",
        "destination_wallet": "DEST",
        "amount_lamports": 1_500_000_000,
        "signature": "SIG",
        "slot": 77,
        "observed_at": datetime(2026, 9, 5, 1, 0, tzinfo=timezone.utc).isoformat(),
        "evidence_basis": "direct_system_program_transfer",
    }

    with patch(
        "entity_resolver.service.fetch_recent_inbound_transfers",
        new=AsyncMock(return_value=[transfer]),
    ) as fetch:
        await service._observe_wallet_funding("DEST")
        await service._observe_wallet_funding("DEST")

    fetch.assert_awaited_once()
    service._relationships.record_funding_observation.assert_awaited_once()
    kwargs = service._relationships.record_funding_observation.await_args.kwargs
    assert kwargs["source_wallet"] == "SOURCE"
    assert kwargs["destination_wallet"] == "DEST"
    assert kwargs["amount_lamports"] == 1_500_000_000
    assert kwargs["signature"] == "SIG"
    assert kwargs["evidence"]["evidence_basis"] == "direct_system_program_transfer"
    assert kwargs["evidence"]["source_event"] == "post_migration.buy"
