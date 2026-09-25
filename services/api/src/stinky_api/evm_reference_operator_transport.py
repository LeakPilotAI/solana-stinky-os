"""Transport adapter for explicit, read-only reference DEX operator invocation."""
from __future__ import annotations

from pydantic import BaseModel, Field

from stinky_api.evm_reference_observation_operator import DurableReferenceDexObservationResult
from stinky_api.evm_reference_observation_trigger import (
    ReferenceDexObservationSchedule,
    ReferenceDexObservationTriggerRequest,
)
from stinky_core.chains import ChainFamily, get_chain
from stinky_core.evm_dex_discovery import DexPoolCandidate
from stinky_core.evm_reference_fingerprints import DexReferenceContractSource
from stinky_core.evm_rpc import EvmReadOnlyRpc
from stinky_core.multichain_identity import asset_key, canonical_chain_address


class ReferenceSourcePayload(BaseModel):
    address: str
    contract_role: str
    implementation_family: str
    implementation_version: str
    source_repository: str
    source_commit: str
    source_path: str
    source_locator: str


class ReferenceDexOperatorPayload(BaseModel):
    chain: str
    chain_id: int = Field(gt=0)
    factory_address: str
    pool_address: str
    token0_address: str
    token1_address: str
    event_family: str
    fee_tier: int | None = Field(default=None, ge=0)
    first_seen_block: int = Field(ge=0)
    block_hash: str
    transaction_hash: str
    log_index: str
    router_address: str
    sources: tuple[ReferenceSourcePayload, ...]
    block_number: int = Field(ge=0)
    min_quorum: int = Field(default=2, ge=2)
    interval_seconds: int = Field(default=300, ge=60)
    enabled: bool = True


def _hex32(value: str, field: str) -> str:
    normalized = str(value or "").lower()
    if len(normalized) != 66 or not normalized.startswith("0x"):
        raise ValueError(f"{field} must be a 32-byte hex value")
    try:
        int(normalized[2:], 16)
    except ValueError as exc:
        raise ValueError(f"{field} must be a 32-byte hex value") from exc
    return normalized


def _canonical_address(chain: str, value: str, field: str) -> str:
    normalized = canonical_chain_address(chain, value)
    if normalized is None:
        raise ValueError(f"{field} must be a canonical address for {chain}")
    return normalized


def _required_text(value: str, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if "<REPLACE_" in normalized.upper():
        raise ValueError(f"{field} contains an unresolved operator template placeholder")
    return normalized


def _build_reference_sources(payload: ReferenceDexOperatorPayload) -> tuple[DexReferenceContractSource, ...]:
    sources = tuple(
        DexReferenceContractSource(
            chain=payload.chain,
            address=source.address,
            contract_role=source.contract_role,
            implementation_family=source.implementation_family,
            implementation_version=source.implementation_version,
            source_repository=source.source_repository,
            source_commit=source.source_commit,
            source_path=source.source_path,
            source_locator=source.source_locator,
        )
        for source in payload.sources
    )
    if not sources:
        raise ValueError("sources must not be empty")
    return sources


def validate_operator_payload(payload: ReferenceDexOperatorPayload) -> dict:
    """Validate an operator payload completely offline without RPC or database access."""
    chain = get_chain(payload.chain)
    if chain is None or chain.family is not ChainFamily.EVM or chain.chain_id is None:
        raise ValueError(f"unsupported EVM chain: {payload.chain!r}")
    if chain.chain_id != payload.chain_id:
        raise ValueError(
            f"chain_id mismatch for {payload.chain}: expected {chain.chain_id}, got {payload.chain_id}"
        )

    factory = _canonical_address(payload.chain, payload.factory_address, "factory_address")
    pool = _canonical_address(payload.chain, payload.pool_address, "pool_address")
    token0 = _canonical_address(payload.chain, payload.token0_address, "token0_address")
    token1 = _canonical_address(payload.chain, payload.token1_address, "token1_address")
    router = _canonical_address(payload.chain, payload.router_address, "router_address")
    if token0 == token1:
        raise ValueError("token0_address and token1_address must differ")

    _required_text(payload.event_family, "event_family")
    _required_text(payload.log_index, "log_index")
    _hex32(payload.block_hash, "block_hash")
    _hex32(payload.transaction_hash, "transaction_hash")

    if not payload.sources:
        raise ValueError("sources must not be empty")
    for index, source in enumerate(payload.sources):
        prefix = f"sources[{index}]"
        _canonical_address(payload.chain, source.address, f"{prefix}.address")
        _required_text(source.contract_role, f"{prefix}.contract_role")
        _required_text(source.implementation_family, f"{prefix}.implementation_family")
        _required_text(source.implementation_version, f"{prefix}.implementation_version")
        _required_text(source.source_repository, f"{prefix}.source_repository")
        _required_text(source.source_commit, f"{prefix}.source_commit")
        _required_text(source.source_path, f"{prefix}.source_path")
        _required_text(source.source_locator, f"{prefix}.source_locator")

    _build_reference_sources(payload)

    return {
        "chain": payload.chain,
        "chain_id": payload.chain_id,
        "factory_address": factory,
        "pool_address": pool,
        "router_address": router,
        "block_number": payload.block_number,
        "min_quorum": payload.min_quorum,
        "source_count": len(payload.sources),
        "validated_offline": True,
        "read_only": True,
        "execution_authorized": False,
    }


def build_operator_request(
    payload: ReferenceDexOperatorPayload,
    observers: tuple[EvmReadOnlyRpc, ...],
) -> tuple[ReferenceDexObservationSchedule, ReferenceDexObservationTriggerRequest]:
    if not isinstance(observers, tuple):
        raise ValueError("operator observers must be an immutable tuple")
    if len(observers) < payload.min_quorum:
        raise ValueError("not enough preconfigured observers for requested quorum")

    factory = _canonical_address(payload.chain, payload.factory_address, "factory_address")
    pool_address = _canonical_address(payload.chain, payload.pool_address, "pool_address")
    token0 = _canonical_address(payload.chain, payload.token0_address, "token0_address")
    token1 = _canonical_address(payload.chain, payload.token1_address, "token1_address")
    router = _canonical_address(payload.chain, payload.router_address, "router_address")
    if token0 == token1:
        raise ValueError("token0_address and token1_address must differ")

    candidate = DexPoolCandidate(
        chain=payload.chain,
        chain_id=payload.chain_id,
        factory_address=factory,
        factory_key=asset_key(payload.chain, factory) or "",
        pool_address=pool_address,
        pool_key=asset_key(payload.chain, pool_address) or "",
        token0_address=token0,
        token0_key=asset_key(payload.chain, token0) or "",
        token1_address=token1,
        token1_key=asset_key(payload.chain, token1) or "",
        event_family=payload.event_family,
        fee_tier=payload.fee_tier,
        first_seen_block=payload.first_seen_block,
        block_hash=_hex32(payload.block_hash, "block_hash"),
        transaction_hash=_hex32(payload.transaction_hash, "transaction_hash"),
        log_index=str(payload.log_index),
        status="UNVERIFIED_DEX_POOL_CANDIDATE",
        evidence_providers=tuple(sorted({observer.rpc_url for observer in observers})),
    )
    sources = _build_reference_sources(payload)

    return (
        ReferenceDexObservationSchedule(
            interval_seconds=payload.interval_seconds,
            enabled=payload.enabled,
        ),
        ReferenceDexObservationTriggerRequest(
            pool=candidate,
            router_address=router,
            sources=sources,
            observers=observers,
            block_number=payload.block_number,
            min_quorum=payload.min_quorum,
        ),
    )


def serialize_operator_result(result: DurableReferenceDexObservationResult) -> dict:
    trigger = result.trigger
    state = result.state
    return {
        "triggered": trigger.triggered,
        "reason": trigger.reason,
        "observed_at": trigger.observed_at.isoformat(),
        "state": None if state is None else {
            "chain": state.chain,
            "pool_address": state.pool_address,
            "last_completed_block": state.last_completed_block,
            "last_completed_at": state.last_completed_at.isoformat(),
        },
        "read_only": True,
        "execution_authorized": False,
    }
