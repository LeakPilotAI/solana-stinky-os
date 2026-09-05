from uuid import uuid4

from entity_resolver.graph import assemble_entity_graph


def test_entity_graph_preserves_relationship_evidence_and_peer_entities() -> None:
    entity_id = uuid4()
    peer_id = uuid4()
    graph = assemble_entity_graph(
        entity={
            "entity_id": entity_id,
            "entity_type": "deployer",
            "display_label": "dep:SOURCE",
            "primary_wallet": "SOURCE",
            "confidence": 0.85,
        },
        wallets=[
            {
                "wallet": "SOURCE",
                "role": "primary",
                "link_reason": "entity_created",
                "confidence": 0.85,
            }
        ],
        relationships=[
            {
                "wallet_a": "SOURCE",
                "wallet_b": "DEST",
                "relationship_kind": "funding_observation",
                "observation_count": 2,
                "first_seen_at": "2026-09-04T01:00:00+00:00",
                "last_seen_at": "2026-09-04T02:00:00+00:00",
                "confidence": 1.0,
                "evidence": {
                    "evidence_basis": "direct_transfer_observation",
                    "signature": "SIG2",
                },
                "entity_a_id": entity_id,
                "entity_b_id": peer_id,
            }
        ],
    )

    assert graph["evidence_only"] is True
    assert graph["entity"]["entity_id"] == str(entity_id)
    assert len(graph["nodes"]) == 2
    assert graph["edges"][0]["relationship_kind"] == "funding_observation"
    assert graph["edges"][0]["observation_count"] == 2
    assert graph["edges"][0]["evidence"]["signature"] == "SIG2"
    assert graph["edges"][0]["entity_b_id"] == peer_id


def test_entity_graph_deduplicates_same_relationship_and_skips_self_edge() -> None:
    entity_id = uuid4()
    relationships = [
        {
            "wallet_a": "A",
            "wallet_b": "B",
            "relationship_kind": "co_early_buy",
            "observation_count": 3,
            "evidence": {"shared_mints": 3},
        },
        {
            "wallet_a": "B",
            "wallet_b": "A",
            "relationship_kind": "co_early_buy",
            "observation_count": 4,
            "evidence": {"shared_mints": 4},
        },
        {
            "wallet_a": "A",
            "wallet_b": "A",
            "relationship_kind": "funding_observation",
            "observation_count": 1,
            "evidence": {},
        },
    ]
    graph = assemble_entity_graph(
        entity={"entity_id": entity_id, "entity_type": "trader"},
        wallets=[{"wallet": "A", "role": "primary"}],
        relationships=relationships,
    )

    assert len(graph["edges"]) == 1
    assert graph["edges"][0]["wallet_a"] == "A"
    assert graph["edges"][0]["wallet_b"] == "B"
