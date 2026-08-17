"""Data Quality Layer (ADR-007).

Validates events before they enter Feature Engineering.
Invalid events are rejected to a dead-letter path and never reach intelligence services.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from stinky_core.events.base import Event, EventType


@dataclass(frozen=True, slots=True)
class ValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    repaired_event: Event | None = None


class EventValidator:
    """Schema + semantic validation for inbound events."""

    REQUIRED_PAYLOAD_KEYS: dict[EventType, set[str]] = {
        # name/symbol optional — pump.fun logs sometimes omit decoded metadata
        EventType.TOKEN_LAUNCH: {"mint", "deployer"},
        EventType.TOKEN_TRANSFER: {"mint", "from_wallet", "to_wallet", "amount"},
        EventType.LIQUIDITY_ADD: {"mint", "wallet", "amount_sol"},
        EventType.LIQUIDITY_REMOVE: {"mint", "wallet", "amount_sol"},
        EventType.BONDING_SUCCESS: {"mint"},
        EventType.TOKEN_MIGRATED: {"mint", "pool"},
        EventType.VOLUME_THRESHOLD: {"mint", "volume_m5_usd"},
        EventType.ALERT_CANDIDATE: {"mint", "reason"},
        EventType.POST_MIGRATION_TRACKING_STARTED: {"mint", "pool"},
        EventType.POST_MIGRATION_BUY: {"mint", "wallet", "signature"},
        EventType.POST_MIGRATION_SELL: {"mint", "wallet", "signature"},
        EventType.POST_MIGRATION_MARKET_SNAPSHOT: {"mint"},
        EventType.POST_MIGRATION_HOLDER_SNAPSHOT: {"mint"},
        EventType.POST_MIGRATION_TRACKING_COMPLETED: {"mint"},
        EventType.WALLET_PERFORMANCE_UPDATED: {"wallet"},
        EventType.SCORE_UPDATED: {"entity_id", "score", "confidence", "model_version"},
        EventType.ENTITY_CREATED: {"entity_id", "entity_type"},
        EventType.WALLET_LINKED: {"entity_id", "wallet_address", "confidence"},
    }

    # Slot is ideal but logsSubscribe paths often lack it initially
    SLOT_REQUIRED_TYPES = {
        EventType.RAW_TRANSACTION,
        EventType.TOKEN_TRANSFER,
        EventType.LIQUIDITY_ADD,
        EventType.LIQUIDITY_REMOVE,
        EventType.BONDING_SUCCESS,
        EventType.RUG_SIGNAL,
    }

    def validate(self, event: Event) -> ValidationResult:
        errors: list[str] = []

        if not event.event_type:
            errors.append("event_type is required")

        required = self.REQUIRED_PAYLOAD_KEYS.get(event.event_type)
        if required:
            missing = required - set(event.payload.keys())
            if missing:
                errors.append(f"missing required payload keys: {sorted(missing)}")

        if event.event_type in self.SLOT_REQUIRED_TYPES and event.slot is None:
            errors.append("slot is required for this chain event type")

        # block_time preferred; defaulted by publishers when missing
        if event.event_type in self.SLOT_REQUIRED_TYPES and event.block_time is None:
            errors.append("block_time is required for this chain event type")

        if event.event_type == EventType.SCORE_UPDATED:
            score = event.payload.get("score")
            conf = event.payload.get("confidence")
            if score is not None and not (0.0 <= float(score) <= 100.0):
                errors.append("score must be in [0, 100]")
            if conf is not None and not (0.0 <= float(conf) <= 1.0):
                errors.append("confidence must be in [0, 1]")

        if errors:
            return ValidationResult(is_valid=False, errors=errors)
        return ValidationResult(is_valid=True)

    def validate_or_raise(self, event: Event) -> Event:
        result = self.validate(event)
        if not result.is_valid:
            raise ValueError(f"Event validation failed: {'; '.join(result.errors)}")
        return event
