"""Read-only HTTP surface for persisted DEX provenance evidence."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.db import get_session
from stinky_api.dex_provenance import read_dex_provenance_response
from stinky_api.dex_provenance_provider import PostgresDexProvenanceEvidenceProvider
from stinky_api.entity_graph import router
from stinky_core.evm_dex_provenance_response import DexProvenanceResponse


@router.get("/dex-provenance/{chain}/{pool_address}", tags=["dex-provenance"])
async def dex_provenance_response(
    chain: str,
    pool_address: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DexProvenanceResponse:
    """Return preserved provenance evidence only; never synthesize missing evidence."""
    provider = PostgresDexProvenanceEvidenceProvider(session)
    try:
        return await read_dex_provenance_response(
            provider,
            chain=chain,
            pool_address=pool_address,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="DEX provenance evidence unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
