from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from stinky_api import evm_provider_attestation_http as http
from stinky_api.evm_provider_attestation_audit import encode_provider_attestation_audit
from stinky_api.main import app
from test_evm_provider_attestation_audit import record


PREFIX = "/v1/entity-graph/provider-attestations"


@pytest.fixture
def harness(monkeypatch):
    original = record()
    row = {"chain": original.chain, "pool_address": original.pool_address,
           "block_number": original.block_number, "completed_at": original.completed_at,
           "audit_payload": encode_provider_attestation_audit(original)}
    state = SimpleNamespace(row=row, sessions=0, queries=[])
    class ReadSession:
        async def __aenter__(self):
            state.sessions += 1
            return self
        async def __aexit__(self, *args):
            pass
        async def execute(self, statement, params):
            sql = str(statement).strip()
            assert sql.startswith("SELECT")
            assert "block_number = :block_number" in sql
            assert all(word not in sql.upper() for word in ("INSERT", "UPDATE", "DELETE"))
            state.queries.append(params)
            selected = state.row if state.row and all(state.row[key] == value for key, value in params.items()) else None
            return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: selected))
        def __getattr__(self, name):
            pytest.fail(f"read-only endpoint attempted session operation {name}")
    monkeypatch.setattr(http, "SessionLocal", ReadSession)
    return TestClient(app), state


def path(chain="base", pool=None, block=123456):
    return f"{PREFIX}/{chain}/{pool or record().pool_address}/{block}"


def test_exact_historical_receipt_read_only_transport(harness):
    client, state = harness
    response = client.get(path())
    assert response.status_code == 200
    assert response.json() == {**encode_provider_attestation_audit(record()),
                               "read_only": True, "execution_authorized": False}
    assert state.sessions == 1
    assert state.queries == [{"chain": "base", "pool_address": record().pool_address, "block_number": 123456}]
    assert all(secret not in response.text for secret in ("SECRET", "https://", "?key=", "/private"))


def test_canonicalized_address_and_chain(harness):
    client, state = harness
    pool = "0x" + "ab" * 20
    state.row["pool_address"] = pool
    state.row["audit_payload"]["pool_address"] = pool
    response = client.get(path(chain="BASE", pool="0x" + "AB" * 20))
    assert response.status_code == 200
    assert response.json()["chain"] == "base"
    assert response.json()["pool_address"] == pool


def test_missing_exact_block_never_falls_back_to_other_evidence(harness):
    client, state = harness
    response = client.get(path(block=123455))
    assert response.status_code == 404
    assert response.json() == {"detail": "provider attestation audit unavailable"}
    assert len(state.queries) == 1 and state.queries[0]["block_number"] == 123455


@pytest.mark.parametrize("request_path", [
    path(chain="unknown"), path(chain="solana"), path(pool="bad-address"),
    path(block=-1), path(block="latest"), path(block=9223372036854775808),
])
def test_invalid_identity_rejected_before_session_or_query(harness, request_path):
    client, state = harness
    assert client.get(request_path).status_code == 422
    assert state.sessions == 0 and state.queries == []


@pytest.mark.parametrize("corruption", ["version", "chain", "block", "time", "secret", "partial", "extra", "malformed"])
def test_corrupt_stored_receipt_is_rejected_without_exposing_payload(harness, corruption):
    client, state = harness
    payload = state.row["audit_payload"]
    if corruption == "version":
        payload["version"] = 999
    elif corruption == "chain":
        payload["chain"] = "unknown"
    elif corruption == "block":
        payload["block_number"] += 1
    elif corruption == "time":
        payload["completed_at"] = "2026-09-15T00:00:00+00:00"
    elif corruption == "secret":
        payload["provider_attestations"][0]["provider"] = "https://rpc.example/SECRET"
    elif corruption == "partial":
        payload["provider_attestations"].pop()
    elif corruption == "extra":
        payload["secret"] = "SECRET"
    else:
        state.row["audit_payload"] = ["SECRET"]
    response = client.get(path())
    assert response.status_code == 422
    assert response.json() == {"detail": "invalid persisted provider attestation audit"}
    assert "SECRET" not in response.text


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_get_only(harness, method):
    client, state = harness
    assert getattr(client, method)(path()).status_code == 405
    assert state.sessions == 0 and state.queries == []
