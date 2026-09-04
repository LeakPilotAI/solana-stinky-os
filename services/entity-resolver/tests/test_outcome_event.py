from entity_resolver.service import EntityService


def test_completion_event_accepts_status_aliases() -> None:
    for key in ("outcome_status", "status", "outcome"):
        mint, status, metadata = EntityService._outcome_payload(
            {"payload": {"mint": "MINT", key: "completed"}}
        )
        assert mint == "MINT"
        assert status == "completed"
        assert metadata[key] == "completed"


def test_completion_event_requires_mint_and_status() -> None:
    assert EntityService._outcome_payload({"payload": {"status": "completed"}}) == (
        None,
        None,
        {},
    )
