"""Versioned, lossless codec for preserved DEX provenance evidence.

Only the explicitly registered Genesis provenance dataclasses below are accepted.
Unknown type tags, missing fields, unexpected fields, malformed tuple encodings, or
unsupported schema versions fail closed rather than being guessed or backfilled.
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass
from types import UnionType
from typing import Any, Mapping, Sequence, get_args, get_origin, get_type_hints

from .evm_contract_code import ContractCodeEvidence, ContractCodeSource
from .evm_dex_family_composition import DexFamilyConsistencyEvidence
from .evm_factory_evidence import FactoryRelationshipEvidence, FactoryRelationshipSource
from .evm_implementation_registry import ImplementationFingerprintEvidence, ImplementationFingerprintMatch
from .evm_reference_dex_envelope import ReferenceDexEvidenceEnvelope
from .evm_reference_dex_record import ReferenceDexEvidenceRecord
from .evm_reference_fingerprints import DexReferenceContractSource

SCHEMA = "GENESIS_DEX_PROVENANCE_EVIDENCE"
VERSION = 1

_SUPPORTED_TYPES = {
    cls.__name__: cls
    for cls in (
        ContractCodeSource,
        ContractCodeEvidence,
        FactoryRelationshipSource,
        FactoryRelationshipEvidence,
        ImplementationFingerprintMatch,
        ImplementationFingerprintEvidence,
        DexFamilyConsistencyEvidence,
        ReferenceDexEvidenceEnvelope,
        ReferenceDexEvidenceRecord,
        DexReferenceContractSource,
    )
}

_FIELD_TYPES = {cls: get_type_hints(cls) for cls in _SUPPORTED_TYPES.values()}


def _matches_type(value: Any, expected: Any) -> bool:
    origin = get_origin(expected)
    args = get_args(expected)
    if origin is UnionType:
        return any(_matches_type(value, option) for option in args)
    if origin is tuple:
        if type(value) is not tuple:
            return False
        if len(args) == 2 and args[1] is Ellipsis:
            return all(_matches_type(item, args[0]) for item in value)
        return len(value) == len(args) and all(
            _matches_type(item, kind) for item, kind in zip(value, args)
        )
    return type(value) is expected


def _validate_fields(cls: type, values: Mapping[str, Any]) -> None:
    if any(not _matches_type(values[name], expected) for name, expected in _FIELD_TYPES[cls].items()):
        raise ValueError("DEX provenance field type does not match schema")


def _encode(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, tuple):
        return {"__tuple__": [_encode(item) for item in value]}
    if is_dataclass(value):
        name = type(value).__name__
        if name not in _SUPPORTED_TYPES or _SUPPORTED_TYPES[name] is not type(value):
            raise ValueError(f"unsupported DEX provenance evidence type: {name}")
        _validate_fields(type(value), {field.name: getattr(value, field.name) for field in fields(value)})
        return {
            "__type__": name,
            "fields": {field.name: _encode(getattr(value, field.name)) for field in fields(value)},
        }
    raise ValueError(f"unsupported DEX provenance evidence value: {type(value).__name__}")


def _decode(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("encoded DEX provenance value must be a mapping or scalar")
    keys = set(value)
    if keys == {"__tuple__"}:
        items = value["__tuple__"]
        if not isinstance(items, list):
            raise ValueError("encoded tuple payload must be a list")
        return tuple(_decode(item) for item in items)
    if keys != {"__type__", "fields"}:
        raise ValueError("encoded DEX provenance object has unsupported structure")
    name = value["__type__"]
    payload = value["fields"]
    if not isinstance(name, str) or name not in _SUPPORTED_TYPES:
        raise ValueError("unknown DEX provenance evidence type")
    if not isinstance(payload, Mapping):
        raise ValueError("encoded DEX provenance fields must be a mapping")
    cls = _SUPPORTED_TYPES[name]
    expected = {field.name for field in fields(cls)}
    actual = set(payload)
    if actual != expected:
        raise ValueError("encoded DEX provenance fields do not match schema")
    decoded = {field.name: _decode(payload[field.name]) for field in fields(cls)}
    _validate_fields(cls, decoded)
    return cls(**decoded)


def encode_reference_dex_evidence_record(record: ReferenceDexEvidenceRecord) -> dict[str, Any]:
    if type(record) is not ReferenceDexEvidenceRecord:
        raise ValueError("DEX provenance payload is not a ReferenceDexEvidenceRecord")
    return {"schema": SCHEMA, "version": VERSION, "value": _encode(record)}


def decode_reference_dex_evidence_record(payload: Mapping[str, Any]) -> ReferenceDexEvidenceRecord:
    if not isinstance(payload, Mapping):
        raise ValueError("DEX provenance record payload must be a mapping")
    if set(payload) != {"schema", "version", "value"}:
        raise ValueError("DEX provenance record payload structure is invalid")
    if payload["schema"] != SCHEMA or type(payload["version"]) is not int or payload["version"] != VERSION:
        raise ValueError("unsupported DEX provenance evidence schema version")
    record = _decode(payload["value"])
    if not isinstance(record, ReferenceDexEvidenceRecord):
        raise ValueError("DEX provenance payload is not a ReferenceDexEvidenceRecord")
    return record


def encode_reference_sources(
    sources: Sequence[DexReferenceContractSource],
) -> tuple[dict[str, Any], ...]:
    if isinstance(sources, (str, bytes)):
        raise ValueError("reference sources must be a sequence")
    source_items = tuple(sources)
    if any(type(source) is not DexReferenceContractSource for source in source_items):
        raise ValueError("reference source payload has wrong type")
    return tuple({"schema": SCHEMA, "version": VERSION, "value": _encode(source)} for source in source_items)


def decode_reference_sources(
    payloads: Sequence[Mapping[str, Any]],
) -> tuple[DexReferenceContractSource, ...]:
    if isinstance(payloads, (str, bytes)):
        raise ValueError("reference source payloads must be a sequence")
    decoded: list[DexReferenceContractSource] = []
    for payload in payloads:
        if not isinstance(payload, Mapping):
            raise ValueError("reference source payload must be a mapping")
        if set(payload) != {"schema", "version", "value"}:
            raise ValueError("reference source payload structure is invalid")
        if payload["schema"] != SCHEMA or type(payload["version"]) is not int or payload["version"] != VERSION:
            raise ValueError("unsupported DEX provenance evidence schema version")
        source = _decode(payload["value"])
        if not isinstance(source, DexReferenceContractSource):
            raise ValueError("reference source payload has wrong type")
        decoded.append(source)
    return tuple(decoded)


def validate_record_identity(
    record: ReferenceDexEvidenceRecord,
    *,
    chain: str,
    pool_address: str,
    evidence_block: int,
) -> None:
    relationship = record.relationship
    if relationship.chain != chain:
        raise ValueError("persisted DEX provenance chain does not match record")
    if relationship.pool_address != pool_address:
        raise ValueError("persisted DEX provenance pool does not match record")
    if relationship.block_number != evidence_block:
        raise ValueError("persisted DEX provenance block does not match record")
    envelope = record.envelope
    if envelope.dex_family.chain != chain or envelope.dex_family.block_number != evidence_block:
        raise ValueError("persisted DEX provenance envelope identity mismatch")
    factory_code = relationship.factory_code
    if (factory_code.chain, factory_code.block_number, factory_code.address) != (
        chain, evidence_block, relationship.factory_address,
    ):
        raise ValueError("persisted DEX provenance factory code identity mismatch")
    components = (
        (envelope.factory_fingerprint, "FACTORY", relationship.factory_address),
        (envelope.pool_fingerprint, "POOL", pool_address),
        (envelope.router_fingerprint, "ROUTER", envelope.router_fingerprint.address),
    )
    for component, role, address in components:
        if (component.chain, component.block_number, component.address, component.expected_role) != (
            chain, evidence_block, address, role,
        ):
            raise ValueError("persisted DEX provenance component identity mismatch")
    if tuple(item for item in envelope.chain_blocks if item[0] == chain) != ((chain, evidence_block),):
        raise ValueError("persisted DEX provenance reference block identity mismatch")
