from fastapi.testclient import TestClient

from stinky_api.main import app


def test_live_readiness_cohort_static_route_is_not_shadowed_by_entity_uuid(monkeypatch):
    async def fake_validation(session, *, entity_limit, snapshot_limit_per_entity, as_of, include_entities):
        return {
            "status": "INSUFFICIENT_CAPTURED_HISTORY",
            "valid": False,
            "counts": {"entity_count": 0},
            "bounded": {
                "entity_limit": entity_limit,
                "snapshot_limit_per_entity": snapshot_limit_per_entity,
            },
            "evidence_only": True,
        }

    monkeypatch.setattr(
        "stinky_api.entity_readiness_live_cohort.live_entity_readiness_cohort_validation",
        fake_validation,
    )

    client = TestClient(app)
    response = client.get(
        "/v1/entity-graph/live-readiness-cohort",
        params={"entity_limit": 500, "snapshot_limit": 200},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["bounded"]["entity_limit"] == 500
    assert payload["bounded"]["snapshot_limit_per_entity"] == 200
    assert "uuid_parsing" not in response.text


def test_dynamic_entity_route_still_rejects_non_uuid_unknown_path():
    client = TestClient(app)
    response = client.get("/v1/entity-graph/not-a-real-entity-id")
    assert response.status_code == 422
