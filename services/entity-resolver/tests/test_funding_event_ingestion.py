from datetime import datetime, timezone

from entity_resolver.service import EntityService


def test_funding_event_requires_explicit_native_sol_identity() -> None:
    event = {
        "event_type": "token.transfer",
        "occurred_at": "2026-09-04T01:02:03Z",
        "signature": "SIG",
        "payload": {
            "asset_type": "SOL",
            "source_wallet": "SOURCE",
            "destination_wallet": "DESTINATION",
            "amount_lamports": 2_500_000_000,
        },
    }
    parsed = EntityService._funding_payload(event)
    assert parsed is not None
    source, destination, observed_at, amount, signature, evidence = parsed
    assert (source, destination) == ("SOURCE", "DESTINATION")
    assert observed_at == datetime(2026, 9, 4, 1, 2, 3, tzinfo=timezone.utc)
    assert amount == 2_500_000_000
    assert signature == "SIG"
    assert evidence["evidence_basis"] == "canonical_token_transfer_event"


def test_funding_event_does_not_guess_spl_token_transfer_as_funding() -> None:
    event = {
        "event_type": "token.transfer",
        "payload": {
            "asset_type": "SPL",
            "source_wallet": "SOURCE",
            "destination_wallet": "DESTINATION",
            "amount_lamports": 2_500_000_000,
        },
    }
    assert EntityService._funding_payload(event) is None


def test_funding_event_requires_both_wallets_and_nonnegative_amount() -> None:
    missing_wallet = {
        "event_type": "token.transfer",
        "payload": {"asset_type": "native", "source_wallet": "SOURCE"},
    }
    negative_amount = {
        "event_type": "token.transfer",
        "payload": {
            "asset_type": "native",
            "source_wallet": "SOURCE",
            "destination_wallet": "DESTINATION",
            "amount_lamports": -1,
        },
    }
    assert EntityService._funding_payload(missing_wallet) is None
    assert EntityService._funding_payload(negative_amount) is None
