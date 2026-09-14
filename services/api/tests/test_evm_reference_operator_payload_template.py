from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from stinky_api.evm_reference_operator_transport import (
    ReferenceDexOperatorPayload,
    build_operator_request,
)


ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = ROOT / "operator" / "base-reference-observation.template.json"


def _load_template() -> dict:
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def test_template_matches_operator_payload_schema_and_contains_no_rpc_or_execution_fields() -> None:
    raw = _load_template()
    payload = ReferenceDexOperatorPayload.model_validate(raw)

    assert payload.chain == "base"
    assert payload.chain_id == 8453
    assert payload.min_quorum == 2
    assert payload.interval_seconds == 300
    assert payload.enabled is True
    assert payload.sources

    serialized = json.dumps(raw).lower()
    for forbidden in (
        "rpc_url",
        "private_key",
        "signer",
        "wallet",
        "transaction_payload",
        "execution_authorized",
        "opportunity_score",
        "admission_decision",
    ):
        assert forbidden not in serialized


def test_unresolved_template_placeholders_fail_closed_before_observation() -> None:
    payload = ReferenceDexOperatorPayload.model_validate(_load_template())
    observers = (
        SimpleNamespace(rpc_url="https://provider-a.invalid"),
        SimpleNamespace(rpc_url="https://provider-b.invalid"),
    )

    with pytest.raises(ValueError, match="factory_address must be a canonical address"):
        build_operator_request(payload, observers)  # type: ignore[arg-type]


def test_template_requires_explicit_historical_block_and_immutable_source_list() -> None:
    raw = _load_template()
    assert "block_number" in raw
    assert isinstance(raw["block_number"], int)
    assert raw["min_quorum"] >= 2
    assert isinstance(raw["sources"], list)
    assert len(raw["sources"]) >= 1
    assert all(isinstance(source, dict) for source in raw["sources"])
