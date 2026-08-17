"""Immutable event definitions for Stinky OS event sourcing.

All intelligence is derived by replaying these events.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from uuid6 import uuid7


class EventType(StrEnum):
    """Canonical event types. New types may be added; never remove or rename."""

    # Ingestion / chain
    RAW_TRANSACTION = "raw.transaction"
    TOKEN_LAUNCH = "token.launch"
    TOKEN_TRANSFER = "token.transfer"
    LIQUIDITY_ADD = "liquidity.add"
    LIQUIDITY_REMOVE = "liquidity.remove"
    BONDING_SUCCESS = "bonding.success"
    TOKEN_MIGRATED = "token.migrated"
    VOLUME_THRESHOLD = "volume.threshold"
    ALERT_CANDIDATE = "alert.candidate"
    RUG_SIGNAL = "rug.signal"

    # Post-migration intelligence collector
    POST_MIGRATION_TRACKING_STARTED = "post_migration.tracking_started"
    POST_MIGRATION_BUY = "post_migration.buy"
    POST_MIGRATION_SELL = "post_migration.sell"
    POST_MIGRATION_MARKET_SNAPSHOT = "post_migration.market_snapshot"
    POST_MIGRATION_HOLDER_SNAPSHOT = "post_migration.holder_snapshot"
    POST_MIGRATION_TRACKING_COMPLETED = "post_migration.tracking_completed"
    WALLET_PERFORMANCE_UPDATED = "wallet.performance_updated"

    # Internal intelligence
    ENTITY_CREATED = "entity.created"
    ENTITY_MERGED = "entity.merged"
    ENTITY_SPLIT = "entity.split"
    WALLET_LINKED = "wallet.linked"
    SCORE_UPDATED = "score.updated"
    FINGERPRINT_OBSERVED = "fingerprint.observed"
    DNA_UPDATED = "dna.updated"
    PATTERN_DISCOVERED = "pattern.discovered"
    PREDICTION_GENERATED = "prediction.generated"

    # System
    DATA_QUALITY_REJECTED = "data_quality.rejected"
    DATA_QUALITY_REPAIRED = "data_quality.repaired"


class Event(BaseModel):
    """Immutable domain event. Never mutated after creation."""

    event_id: UUID = Field(default_factory=uuid7)
    event_type: EventType
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    # Solana-specific provenance
    slot: int | None = None
    block_time: datetime | None = None
    signature: str | None = None
    # Payload is versioned and schema-validated downstream
    payload: dict[str, Any] = Field(default_factory=dict)
    # Schema version of this event shape
    schema_version: str = "1.0.0"
    # Traceability
    correlation_id: UUID | None = None
    causation_id: UUID | None = None
    producer: str = "unknown"

    model_config = {"frozen": True}

    @field_validator("occurred_at", "block_time", mode="before")
    @classmethod
    def ensure_utc(cls, v: datetime | str | None) -> datetime | None:
        if v is None:
            return v
        if isinstance(v, str):
            # Handle ISO strings produced by orjson / model_dump
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class EventEnvelope(BaseModel):
    """Wire-level envelope that travels on the transport."""

    event: Event
    # Transport metadata (not part of domain event)
    published_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    attempt: int = 1
    transport_headers: dict[str, str] = Field(default_factory=dict)

    model_config = {"frozen": True}

    def to_bytes(self) -> bytes:
        """Serialize with orjson for high throughput."""
        import orjson

        return orjson.dumps(self.model_dump(mode="json"))

    @classmethod
    def from_bytes(cls, data: bytes) -> EventEnvelope:
        import orjson

        return cls.model_validate(orjson.loads(data))
