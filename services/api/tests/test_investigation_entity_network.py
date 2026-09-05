import pytest

from stinky_api.investigation_entity_network import entity_network_for_investigation


class ExplodingSession:
    async def execute(self, *args, **kwargs):
        raise AssertionError("database should not be queried without an entity id or creator wallet")


@pytest.mark.asyncio
async def test_unknown_investigation_entity_is_explicit_and_bounded():
    result = await entity_network_for_investigation(
        ExplodingSession(),
        wallet_limit=0,
        relationship_limit=999,
    )

    assert result["status"] == "NEW-UNKNOWN"
    assert result["evidence_only"] is True
    assert result["missing"] == ["entity_history"]
    assert result["bounded"] == {"wallet_limit": 1, "relationship_limit": 500}


@pytest.mark.asyncio
async def test_invalid_entity_id_falls_back_to_creator_wallet():
    class Session:
        def __init__(self):
            self.queried = False

        async def execute(self, *args, **kwargs):
            self.queried = True
            class Result:
                def first(self):
                    return None
            return Result()

    session = Session()
    result = await entity_network_for_investigation(
        session,
        entity_id="not-a-uuid",
        creator_wallet="creator-wallet",
    )

    assert session.queried is True
    assert result["status"] == "NEW-UNKNOWN"
    assert result["evidence_only"] is True
