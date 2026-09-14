"""Append-only receipts for completed explicit read-only observations."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_core.chains import ChainFamily, get_chain
from stinky_core.multichain_identity import canonical_chain_address


@dataclass(frozen=True, slots=True)
class ProviderAttestationReceipt:
    provider: str
    chain: str
    chain_id: int
    attested: bool = True


def validate_provider_attestations(receipts, *, chain: str, provider_count: int) -> None:
    configured = get_chain(chain) if isinstance(chain, str) else None
    if configured is None or configured.key != chain or configured.family != ChainFamily.EVM:
        raise ValueError("canonical EVM chain required")
    if type(provider_count) is not int or provider_count < 2:
        raise ValueError("at least two configured providers required")
    if not isinstance(receipts, tuple) or len(receipts) != provider_count:
        raise ValueError("complete immutable provider attestation set required")
    for row in receipts:
        if not isinstance(row, ProviderAttestationReceipt):
            raise ValueError("typed provider receipt required")
        if (row.chain != chain or type(row.chain_id) is not int
                or row.chain_id != configured.chain_id or row.attested is not True):
            raise ValueError("successful matching chain attestation required")
        # Accept only the existing hostname/IPv6 + truncated digest label format.
        if not isinstance(row.provider, str) or not re.fullmatch(r"[a-z0-9.:-]+:[0-9a-f]{12}", row.provider):
            raise ValueError("redacted provider fingerprint required")
    labels = tuple(row.provider for row in receipts)
    if labels != tuple(sorted(set(labels))):
        raise ValueError("provider attestations must be distinct and sorted")


@dataclass(frozen=True, slots=True)
class ProviderAttestationAudit:
    chain: str
    pool_address: str
    block_number: int
    completed_at: datetime
    provider_count: int
    provider_attestations: tuple[ProviderAttestationReceipt, ...]

    def __post_init__(self) -> None:
        validate_provider_attestations(
            self.provider_attestations, chain=self.chain, provider_count=self.provider_count,
        )
        if not isinstance(self.pool_address, str) or not self.pool_address or canonical_chain_address(self.chain, self.pool_address) != self.pool_address:
            raise ValueError("canonical pool address required")
        if type(self.block_number) is not int or self.block_number < 0:
            raise ValueError("non-negative historical block required")
        if not isinstance(self.completed_at, datetime) or self.completed_at.utcoffset() is None:
            raise ValueError("timezone-aware completion timestamp required")


def encode_provider_attestation_audit(record: ProviderAttestationAudit) -> dict:
    # Revalidate before writing even if a caller has bypassed frozen construction.
    record.__post_init__()
    return {
        "version": 1,
        "chain": record.chain,
        "pool_address": record.pool_address,
        "block_number": record.block_number,
        "completed_at": record.completed_at.astimezone(timezone.utc).isoformat(),
        "provider_count": record.provider_count,
        "provider_attestations": [asdict(row) for row in record.provider_attestations],
    }


def decode_provider_attestation_audit(payload: dict) -> ProviderAttestationAudit:
    fields = {"version", "chain", "pool_address", "block_number", "completed_at",
              "provider_count", "provider_attestations"}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError("invalid provider audit fields")
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise ValueError("unsupported provider audit version")
    rows = payload["provider_attestations"]
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or set(row) != {"provider", "chain", "chain_id", "attested"}
        for row in rows
    ):
        raise ValueError("invalid provider audit receipts")
    try:
        return ProviderAttestationAudit(
            chain=payload["chain"], pool_address=payload["pool_address"],
            block_number=payload["block_number"],
            completed_at=datetime.fromisoformat(payload["completed_at"]),
            provider_count=payload["provider_count"],
            provider_attestations=tuple(ProviderAttestationReceipt(**row) for row in rows),
        )
    except (TypeError, KeyError) as exc:
        raise ValueError("malformed provider audit") from exc


async def append_provider_attestation_audit(session: AsyncSession, record: ProviderAttestationAudit) -> None:
    payload = encode_provider_attestation_audit(record)
    await session.execute(text("""
        INSERT INTO evm_provider_attestation_audit
            (chain, pool_address, block_number, completed_at, audit_payload)
        VALUES (:chain, :pool_address, :block_number, :completed_at, CAST(:payload AS JSONB))
    """), {
        "chain": record.chain, "pool_address": record.pool_address,
        "block_number": record.block_number, "completed_at": record.completed_at,
        "payload": json.dumps(payload, sort_keys=True, separators=(",", ":")),
    })


async def load_provider_attestation_audit(
    session: AsyncSession, *, chain: str, pool_address: str, block_number: int,
) -> ProviderAttestationAudit | None:
    result = await session.execute(text("""
        SELECT chain, pool_address, block_number, completed_at, audit_payload
        FROM evm_provider_attestation_audit
        WHERE chain = :chain AND pool_address = :pool_address AND block_number = :block_number
    """), {"chain": chain, "pool_address": pool_address, "block_number": block_number})
    row = result.mappings().first()
    if row is None:
        return None
    record = decode_provider_attestation_audit(row["audit_payload"])
    if (record.chain, record.pool_address, record.block_number, record.completed_at) != (
        row["chain"], row["pool_address"], row["block_number"], row["completed_at"],
    ) or (record.chain, record.pool_address, record.block_number) != (chain, pool_address, block_number):
        raise ValueError("persisted provider audit identity mismatch")
    return record
