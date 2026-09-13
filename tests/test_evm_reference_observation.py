from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

import stinky_core.evm_reference_observation as reference_observation
from stinky_core.evm_contract_code import ContractCodeEvidence, ContractCodeSource
from stinky_core.evm_reference_fingerprints import BASE_UNISWAP_REFERENCE_SOURCES


class Observer:
    def __init__(self, chain):
        self.chain = type("Chain", (), {"key": chain})()


def measured(chain, address, block):
    return ContractCodeEvidence(
        chain=chain,
        chain_id=8453,
        address=address,
        contract_key=f"{chain}:{address}",
        block_number=block,
        byte_length=2,
        fingerprint_sha256="a" * 64,
        runtime_bytecode="0x6001",
        status="UNVERIFIED_CONTRACT_CODE_EVIDENCE",
        sources=(ContractCodeSource("provider-a", "a" * 64, 2), ContractCodeSource("provider-b", "a" * 64, 2)),
    )


def test_reference_observation_preserves_explicit_snapshot(monkeypatch):
    calls = []

    def fake_observe(observers, *, chain, address, block_number, min_quorum):
        calls.append((chain, address, block_number, min_quorum, len(tuple(observers))))
        return measured(chain, address, block_number)

    monkeypatch.setattr(reference_observation, "observe_contract_code", fake_observe)
    bundle = reference_observation.observe_reference_fingerprint_bundle(
        BASE_UNISWAP_REFERENCE_SOURCES,
        {"base": (Observer("base"), Observer("base"))},
        block_numbers={"base": 123456},
    )
    assert len(calls) == len(BASE_UNISWAP_REFERENCE_SOURCES)
    assert all(call[2:] == (123456, 2, 2) for call in calls)
    assert bundle.chain_blocks == (("base", 123456),)
    assert len(bundle.entries) == len(BASE_UNISWAP_REFERENCE_SOURCES)


def test_reference_observation_validates_maps_before_measurement(monkeypatch):
    monkeypatch.setattr(reference_observation, "observe_contract_code", lambda *args, **kwargs: None)
    rows = (Observer("base"), Observer("base"))
    with pytest.raises(ValueError, match="block map"):
        reference_observation.observe_reference_fingerprint_bundle(
            BASE_UNISWAP_REFERENCE_SOURCES,
            {"base": rows},
            block_numbers={},
        )
    with pytest.raises(ValueError, match="observer map"):
        reference_observation.observe_reference_fingerprint_bundle(
            BASE_UNISWAP_REFERENCE_SOURCES,
            {},
            block_numbers={"base": 100},
        )


def test_reference_observation_validates_observer_chain_and_duplicates(monkeypatch):
    monkeypatch.setattr(reference_observation, "observe_contract_code", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="observer chain"):
        reference_observation.observe_reference_fingerprint_bundle(
            BASE_UNISWAP_REFERENCE_SOURCES,
            {"base": (Observer("robinhood"), Observer("robinhood"))},
            block_numbers={"base": 100},
        )
    source = BASE_UNISWAP_REFERENCE_SOURCES[0]
    with pytest.raises(ValueError, match="duplicate reference source"):
        reference_observation.observe_reference_fingerprint_bundle(
            (source, source),
            {"base": (Observer("base"), Observer("base"))},
            block_numbers={"base": 100},
        )


def test_reference_observation_validates_quorum_and_block_values(monkeypatch):
    monkeypatch.setattr(reference_observation, "observe_contract_code", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="enough RPC observers"):
        reference_observation.observe_reference_fingerprint_bundle(
            BASE_UNISWAP_REFERENCE_SOURCES,
            {"base": (Observer("base"),)},
            block_numbers={"base": 100},
        )
    with pytest.raises(ValueError, match="non-negative integers"):
        reference_observation.observe_reference_fingerprint_bundle(
            BASE_UNISWAP_REFERENCE_SOURCES,
            {"base": (Observer("base"), Observer("base"))},
            block_numbers={"base": -1},
        )
