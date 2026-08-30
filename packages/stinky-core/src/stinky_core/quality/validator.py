"""Data Quality Layer (ADR-007).

Validates events and market rows before they enter intelligence.
Invalid data is rejected / quarantined. Never repaired into a pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

try:
    from stinky_core.events.base import Event, EventType
except ImportError:  # pragma: no cover - 3.10 without StrEnum
    Event = Any  # type: ignore[misc,assignment]
    EventType = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    repaired_event: Any = None


_MINT_OK = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")


def _is_solana_address(raw: Any) -> bool:
    if not isinstance(raw, str):
        return False
    s = raw.strip()
    if len(s) < 32 or len(s) > 44:
        return False
    return all(c in _MINT_OK for c in s)


def validate_market_row(row: dict[str, Any]) -> ValidationResult:
    """Quarantine impossible market values before scoring / alerting."""
    errors: list[str] = []
    mint = row.get("mint")
    if not _is_solana_address(mint):
        errors.append("invalid Solana mint")
    for key in ("liquidity_usd", "volume_usd", "volume_m5_usd", "market_cap_usd", "global_fees_sol"):
        v = row.get(key)
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            errors.append(f"{key} is not numeric")
            continue
        if f != f:
            errors.append(f"{key} is NaN")
        elif f < 0:
            errors.append(f"{key} is negative")
    score = row.get("stinky_score") or row.get("score")
    if score is not None:
        try:
            s = float(score)
            if not (0.0 <= s <= 100.0):
                errors.append("score must be in [0, 100]")
        except (TypeError, ValueError):
            errors.append("score is not numeric")
    conf = row.get("confidence")
    if conf is not None:
        try:
            c = float(conf)
            if not (0.0 <= c <= 1.0):
                errors.append("confidence must be in [0, 1]")
        except (TypeError, ValueError):
            errors.append("confidence is not numeric")
    ts = row.get("captured_at") or row.get("evaluated_at")
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            errors.append("timestamp missing timezone")
        elif ts > datetime.now(timezone.utc).replace(year=datetime.now().year + 2):
            errors.append("impossible future timestamp")
    if errors:
        return ValidationResult(is_valid=False, errors=errors)
    return ValidationResult(is_valid=True)


class EventValidator:
    """Schema + semantic validation for inbound events."""

    REQUIRED_PAYLOAD_KEYS: dict[Any, set[str]] = {}
    SLOT_REQUIRED_TYPES: set[Any] = set()

    def __init__(self) -> None:
        if EventType is None:
            return
        self.REQUIRED_PAYLOAD_KEYS = {
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
        self.SLOT_REQUIRED_TYPES = {
            EventType.RAW_TRANSACTION,
            EventType.TOKEN_LAUNCH,
            EventType.TOKEN_TRANSFER,
            EventType.LIQUIDITY_ADD,
            EventType.LIQUIDITY_REMOVE,
            EventType.BONDING_SUCCESS,
            EventType.RUG_SIGNAL,
        }

    def validate(self, event: Any) -> ValidationResult:
        errors: list[str] = []

        if not getattr(event, "event_type", None):
            errors.append("event_type is required")

        required = self.REQUIRED_PAYLOAD_KEYS.get(getattr(event, "event_type", None))
        payload = getattr(event, "payload", {}) or {}
        if required:
            missing = required - set(payload.keys())
            if missing:
                errors.append(f"missing required payload keys: {sorted(missing)}")

        if getattr(event, "event_type", None) in self.SLOT_REQUIRED_TYPES and getattr(event, "slot", None) is None:
            errors.append("slot is required for this chain event type")

        if getattr(event, "event_type", None) in self.SLOT_REQUIRED_TYPES and getattr(event, "block_time", None) is None:
            errors.append("block_time is required for this chain event type")

        if EventType is not None and getattr(event, "event_type", None) == EventType.SCORE_UPDATED:
            score = payload.get("score")
            conf = payload.get("confidence")
            if score is not None and not (0.0 <= float(score) <= 100.0):
                errors.append("score must be in [0, 100]")
            if conf is not None and not (0.0 <= float(conf) <= 1.0):
                errors.append("confidence must be in [0, 1]")

        if errors:
            return ValidationResult(is_valid=False, errors=errors)
        return ValidationResult(is_valid=True)

    def validate_or_raise(self, event: Any) -> Any:
        result = self.validate(event)
        if not result.is_valid:
            raise ValueError(f"Event validation failed: {'; '.join(result.errors)}")
        return event
