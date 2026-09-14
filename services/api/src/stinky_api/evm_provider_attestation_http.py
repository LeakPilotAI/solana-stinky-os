"""Exact historical, read-only access to completed provider attestation receipts."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.db import SessionLocal
from stinky_api.entity_graph import router
from stinky_api.evm_provider_attestation_audit import (
    encode_provider_attestation_audit,
    load_provider_attestation_audit,
)
from stinky_core.chains import ChainFamily, get_chain
from stinky_core.multichain_identity import canonical_chain_address


def audit_identity(
    chain: str, pool_address: str,
    block_number: Annotated[int, Path(ge=0, le=9223372036854775807)],
) -> tuple[str, str, int]:
    configured = get_chain(chain)
    if configured is None or configured.family != ChainFamily.EVM:
        raise HTTPException(status_code=422, detail="invalid EVM audit chain/pool identity")
    pool = canonical_chain_address(configured.key, pool_address)
    if pool is None:
        raise HTTPException(status_code=422, detail="invalid EVM audit chain/pool identity")
    return configured.key, pool, block_number


async def audit_read_session(identity: Annotated[tuple[str, str, int], Depends(audit_identity)]):
    # Identity validation precedes even session creation. This retrieval path
    # closes its SELECT-only transaction without the shared write-session commit.
    async with SessionLocal() as session:
        yield session


@router.get("/provider-attestations/{chain}/{pool_address}/{block_number}", tags=["dex-provenance"])
async def provider_attestation_response(
    identity: Annotated[tuple[str, str, int], Depends(audit_identity)],
    session: Annotated[AsyncSession, Depends(audit_read_session)],
) -> dict:
    chain, pool_address, block_number = identity
    try:
        record = await load_provider_attestation_audit(
            session, chain=chain, pool_address=pool_address, block_number=block_number,
        )
        if record is None:
            raise HTTPException(status_code=404, detail="provider attestation audit unavailable")
        response = encode_provider_attestation_audit(record)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=422, detail="invalid persisted provider attestation audit") from exc
    return {**response, "read_only": True, "execution_authorized": False}
