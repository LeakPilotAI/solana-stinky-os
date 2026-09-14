from fastapi.testclient import TestClient

import stinky_api.dex_provenance_http as http_module
from stinky_api.db import get_session
from stinky_api.main import app

POOL = "0x1111111111111111111111111111111111111111"
PATH = f"/v1/entity-graph/dex-provenance/base/{POOL}"


class ReadOnlySession:
    def __getattr__(self, name):
        if name in {"add", "add_all", "delete", "commit", "flush"}:
            raise AssertionError(f"HTTP provenance endpoint attempted write method: {name}")
        raise AttributeError(name)


async def _session_override():
    yield ReadOnlySession()


def _client():
    app.dependency_overrides[get_session] = _session_override
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_http_endpoint_returns_transport_safe_provenance_only(monkeypatch):
    expected = {
        "category": "UNKNOWN_OR_INSUFFICIENT_PROVENANCE",
        "profile_verdict": "UNKNOWN_DEX_PROVENANCE_PROFILE",
        "strict_lineage_verdict": "UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY",
        "pool_evidence_tier_verdict": "UNKNOWN_POOL_DEPLOYMENT_EVIDENCE",
        "factory_attestation_verdict": "UNKNOWN_FACTORY_ATTESTED_POOL_DEPLOYMENT",
        "status": "DESCRIPTIVE_NON_EXECUTION_PROVENANCE_INTERPRETATION",
        "limitations": ["NOT_EXECUTION_AUTHORIZATION"],
    }
    calls = []

    async def fake_read(provider, *, chain, pool_address):
        calls.append((provider, chain, pool_address))
        assert isinstance(provider._session, ReadOnlySession)
        return expected

    monkeypatch.setattr(http_module, "read_dex_provenance_response", fake_read)
    response = _client().get(PATH)

    assert response.status_code == 200
    assert response.json() == expected
    assert calls and calls[0][1:] == ("base", POOL)
    assert set(response.json()) == {
        "category",
        "profile_verdict",
        "strict_lineage_verdict",
        "pool_evidence_tier_verdict",
        "factory_attestation_verdict",
        "status",
        "limitations",
    }


def test_http_endpoint_maps_missing_evidence_to_404(monkeypatch):
    async def fake_read(provider, *, chain, pool_address):
        raise LookupError("missing")

    monkeypatch.setattr(http_module, "read_dex_provenance_response", fake_read)
    response = _client().get(PATH)

    assert response.status_code == 404
    assert response.json() == {"detail": "DEX provenance evidence unavailable"}


def test_http_endpoint_rejects_malformed_identity_before_provider(monkeypatch):
    called = False

    async def fake_read(provider, *, chain, pool_address):
        nonlocal called
        called = True
        raise AssertionError("malformed identity must not reach provider")

    monkeypatch.setattr(http_module, "read_dex_provenance_response", fake_read)
    response = _client().get("/v1/entity-graph/dex-provenance/base/not-a-valid-pool")

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid DEX provenance chain/pool identity"}
    assert called is False


def test_http_endpoint_is_get_only():
    response = _client().post(PATH)
    assert response.status_code == 405
