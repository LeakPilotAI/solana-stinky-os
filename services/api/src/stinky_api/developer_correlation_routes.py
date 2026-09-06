"""Read-only developer correlation routes backed by canonical investigation evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.db import get_session
from stinky_api.investigation_entity_network import entity_network_for_investigation

router = APIRouter(prefix="/v1/developer-correlation", tags=["developer-correlation"])


@router.get("/{entity_id}")
async def developer_correlation_for_entity(
    entity_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    as_of: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=200),
) -> dict[str, Any]:
    """Return bounded descriptive developer correlation from the canonical investigation graph."""
    network = await entity_network_for_investigation(
        session,
        entity_id=str(entity_id),
        wallet_limit=min(100, limit),
        relationship_limit=limit,
        as_of=as_of,
    )
    correlation = network.get("developer_identity_correlation")
    if not isinstance(correlation, dict):
        correlation = {
            "status": "UNKNOWN",
            "entity_id": str(entity_id),
            "wallets": [],
            "shared_funders": [],
            "cross_entity_wallet_reuse": [],
            "deployer_buyer_recurrence": [],
            "shared_relationship_structures": [],
            "missing": ["developer_identity_correlation"],
            "bounded": {"limit": limit},
            "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
            "ownership_inferred": False,
            "coordination_inferred": False,
            "intent_inferred": False,
            "risk_inferred": False,
            "quality_inferred": False,
            "predictive_authority": False,
            "trade_signal": False,
            "evidence_only": True,
        }
    if correlation.get("entity_id") not in (None, str(entity_id)):
        raise HTTPException(status_code=409, detail="correlation entity mismatch")
    return correlation
