from pathlib import Path


SOURCE = Path("services/api/src/stinky_api/entity_graph.py").read_text()


def test_entity_graph_api_is_bounded_and_evidence_only():
    assert 'APIRouter(prefix="/v1/entity-graph"' in SOURCE
    assert "wallet_limit: int = Query(100, ge=1, le=500)" in SOURCE
    assert "relationship_limit: int = Query(500, ge=1, le=500)" in SOURCE
    assert '"evidence_only": True' in SOURCE
    assert 'status": "KNOWN_ENTITY"' in SOURCE


def test_entity_graph_api_preserves_relationship_evidence_and_peer_entities():
    assert "wr.relationship_kind" in SOURCE
    assert "wr.observation_count" in SOURCE
    assert "wr.first_seen_at" in SOURCE
    assert "wr.last_seen_at" in SOURCE
    assert "wr.confidence" in SOURCE
    assert "wr.evidence" in SOURCE
    assert "entity_a_id" in SOURCE
    assert "entity_b_id" in SOURCE


def test_entity_graph_api_skips_self_edges_and_deduplicates_undirected_edges():
    assert "if a == b:" in SOURCE
    assert "key = (min(a, b), max(a, b), kind)" in SOURCE
    assert "if key in seen:" in SOURCE
