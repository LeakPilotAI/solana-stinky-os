import json

import pytest

from entity_resolver.service import EntityService


def test_parse_stream_event_unwraps_canonical_event_envelope() -> None:
    raw = json.dumps(
        {
            "event": {
                "event_type": "token.migrated",
                "occurred_at": "2026-09-06T12:11:12.532944Z",
                "payload": {
                    "mint": "MINT",
                    "creator": "CREATOR",
                },
            }
        }
    )

    event = EntityService._parse_stream_event(raw)

    assert event["event_type"] == "token.migrated"
    assert event["payload"] == {"mint": "MINT", "creator": "CREATOR"}


def test_parse_stream_event_preserves_direct_event_shape() -> None:
    raw = json.dumps(
        {
            "event_type": "token.migrated",
            "payload": {"mint": "MINT", "creator": "CREATOR"},
        }
    )

    event = EntityService._parse_stream_event(raw)

    assert event["event_type"] == "token.migrated"
    assert event["payload"]["creator"] == "CREATOR"


def test_parse_stream_event_rejects_non_object_json() -> None:
    with pytest.raises(ValueError, match="stream event must decode to an object"):
        EntityService._parse_stream_event(json.dumps(["token.migrated"]))
