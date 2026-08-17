"""Feature Engineering Engine core.

Consumes validated events, maintains lightweight entity context,
computes versioned feature vectors, and persists them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_core.events.base import Event, EventType
from stinky_core.transport.base import EventTransport

from feature_engine.definitions import (
    FEATURE_DEF_VERSION,
    FEATURE_SET_HASH,
    compute_feature_vector,
)

logger = structlog.get_logger(__name__)


class FeatureEngine:
    """Deterministic feature materialization (ADR-005, ADR-006)."""

    def __init__(
        self,
        session: AsyncSession,
        transport: EventTransport,
    ) -> None:
        self._session = session
        self._transport = transport
        # In-memory context cache for V1 (entity_id -> running stats).
        # Production will load from Postgres projections.
        self._context: dict[str, dict[str, Any]] = {}

    def _entity_key(self, event: Event) -> str | None:
        payload = event.payload
        if "entity_id" in payload:
            return str(payload["entity_id"])
        if "deployer" in payload:
            return f"wallet:{payload['deployer']}"
        return None

    def _update_context(self, key: str, event: Event) -> dict[str, Any]:
        ctx = self._context.setdefault(
            key,
            {
                "launch_count": 0,
                "bonded_count": 0,
                "rug_count": 0,
                "median_ath_multiple": 0.0,
                "wallet_age_days": 0.0,
                "unique_funding_sources": 0,
                "repeat_buyer_ratio": 0.0,
                "ath_samples": [],
            },
        )

        if event.event_type == EventType.TOKEN_LAUNCH:
            ctx["launch_count"] = int(ctx["launch_count"]) + 1

        if event.event_type == EventType.BONDING_SUCCESS:
            ctx["bonded_count"] = int(ctx["bonded_count"]) + 1

        if event.event_type == EventType.RUG_SIGNAL:
            ctx["rug_count"] = int(ctx["rug_count"]) + 1

        # Optional richer payload fields
        if "ath_multiple" in event.payload:
            samples: list[float] = list(ctx.get("ath_samples", []))
            samples.append(float(event.payload["ath_multiple"]))
            samples = samples[-100:]  # keep last 100
            ctx["ath_samples"] = samples
            if samples:
                sorted_s = sorted(samples)
                mid = len(sorted_s) // 2
                ctx["median_ath_multiple"] = (
                    sorted_s[mid]
                    if len(sorted_s) % 2
                    else (sorted_s[mid - 1] + sorted_s[mid]) / 2
                )

        for field in (
            "wallet_age_days",
            "unique_funding_sources",
            "repeat_buyer_ratio",
        ):
            if field in event.payload:
                ctx[field] = event.payload[field]

        return ctx

    async def process_event(self, event: Event) -> dict[str, Any] | None:
        """Update context, compute features, persist, and emit event."""
        key = self._entity_key(event)
        if key is None:
            logger.debug("feature.skip_no_entity", event_type=event.event_type)
            return None

        ctx = self._update_context(key, event)
        values = compute_feature_vector(ctx)

        feature_id = uuid4()
        entity_id = event.payload.get("entity_id") or key

        await self._session.execute(
            text(
                """
                INSERT INTO features (
                    feature_id, entity_id, feature_set_hash,
                    feature_def_version, values, computed_at
                ) VALUES (
                    :feature_id, :entity_id, :feature_set_hash,
                    :feature_def_version, CAST(:values AS jsonb), :computed_at
                )
                """
            ),
            {
                "feature_id": str(feature_id),
                "entity_id": str(entity_id),
                "feature_set_hash": FEATURE_SET_HASH,
                "feature_def_version": FEATURE_DEF_VERSION,
                "values": __import__("orjson").dumps(values).decode(),
                "computed_at": datetime.now(timezone.utc),
            },
        )
        await self._session.commit()

        # Emit internal event so Score Engine can react
        out = Event(
            event_type=EventType.SCORE_UPDATED,  # placeholder until dedicated type
            payload={
                "entity_id": str(entity_id),
                "feature_id": str(feature_id),
                "feature_set_hash": FEATURE_SET_HASH,
                "feature_def_version": FEATURE_DEF_VERSION,
                "values": values,
            },
            producer="feature-engine",
            correlation_id=event.event_id,
            causation_id=event.event_id,
        )
        # Use a more appropriate type when available; for now we only signal update
        # Prefer a dedicated FEATURE_UPDATED later. For V1 we publish via transport
        # only if downstream expects it – keep deterministic.
        logger.info(
            "features.materialized",
            entity_id=str(entity_id),
            feature_id=str(feature_id),
            feature_set_hash=FEATURE_SET_HASH,
            launch_count=values.get("launch_count"),
            bond_rate=values.get("bond_rate"),
        )
        return values
