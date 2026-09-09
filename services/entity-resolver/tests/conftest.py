from __future__ import annotations

import pytest

from entity_resolver import chain_evidence


@pytest.fixture(autouse=True)
def clear_funding_wallet_cooldowns():
    """Prevent module-level deferred-wallet state from leaking across tests."""
    chain_evidence._funding_wallet_deferred_until.clear()
    yield
    chain_evidence._funding_wallet_deferred_until.clear()
