"""Validated operator/schedule seam for read-only reference DEX observation.

This module deliberately does not create a background loop, signer, wallet, transaction
sender, admission decision, opportunity score, or execution authority. It gives runtime
callers one deterministic place to decide whether a configured observation is due and,
when explicitly invoked, delegates the complete evidence operation to execution #248.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.evm_reference_observation_runner import (
    ReferenceDexObservationRun,
    observe_and_persist_reference_dex_evidence,
)
from stinky_core.evm_dex_discovery import DexPoolCandidate
from stinky_core.evm_reference_fingerprints import DexReferenceContractSource
from stinky_core.evm_rpc import EvmReadOnlyRpc


@dataclass(frozen=True, slots=True)
class ReferenceDexObservationSchedule:
    interval_seconds: int
    enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.interval_seconds, int) or isinstance(self.interval_seconds, bool):
            raise ValueError("interval_seconds must be an integer")
        if self.interval_seconds < 60:
            raise ValueError("interval_seconds must be at least 60")


@dataclass(frozen=True, slots=True)
class ReferenceDexObservationTriggerRequest:
    pool: DexPoolCandidate
    router_address: str
    sources: tuple[DexReferenceContractSource, ...]
    observers: tuple[EvmReadOnlyRpc, ...]
    block_number: int
    min_quorum: int = 2

    def __post_init__(self) -> None:
        if not isinstance(self.sources, tuple):
            raise ValueError("trigger sources must be an immutable tuple")
        if not isinstance(self.observers, tuple):
            raise ValueError("trigger observers must be an immutable tuple")


@dataclass(frozen=True, slots=True)
class ReferenceDexObservationTriggerResult:
    triggered: bool
    reason: str
    observed_at: datetime
    run: ReferenceDexObservationRun | None


def _require_aware_utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def reference_observation_is_due(
    schedule: ReferenceDexObservationSchedule,
    *,
    now: datetime,
    last_completed_at: datetime | None,
) -> bool:
    """Return whether one read-only observation is due; never performs I/O."""
    if not schedule.enabled:
        return False
    current = _require_aware_utc(now, field="now")
    if last_completed_at is None:
        return True
    previous = _require_aware_utc(last_completed_at, field="last_completed_at")
    if current < previous:
        raise ValueError("now must not be earlier than last_completed_at")
    return (current - previous).total_seconds() >= schedule.interval_seconds


async def trigger_reference_dex_observation(
    session: AsyncSession,
    *,
    request: ReferenceDexObservationTriggerRequest,
    observed_at: datetime,
) -> ReferenceDexObservationTriggerResult:
    """Explicitly trigger exactly one #248 observation run."""
    observed = _require_aware_utc(observed_at, field="observed_at")
    run = await observe_and_persist_reference_dex_evidence(
        session,
        pool=request.pool,
        router_address=request.router_address,
        sources=request.sources,
        observers=request.observers,
        block_number=request.block_number,
        min_quorum=request.min_quorum,
    )
    return ReferenceDexObservationTriggerResult(
        triggered=True,
        reason="OPERATOR_TRIGGERED_REFERENCE_DEX_OBSERVATION",
        observed_at=observed,
        run=run,
    )


async def run_reference_dex_observation_if_due(
    session: AsyncSession,
    *,
    schedule: ReferenceDexObservationSchedule,
    request: ReferenceDexObservationTriggerRequest,
    now: datetime,
    last_completed_at: datetime | None,
) -> ReferenceDexObservationTriggerResult:
    """Run at most once when due; callers own any external timer/loop."""
    observed = _require_aware_utc(now, field="now")
    if not reference_observation_is_due(
        schedule,
        now=observed,
        last_completed_at=last_completed_at,
    ):
        reason = (
            "REFERENCE_DEX_OBSERVATION_DISABLED"
            if not schedule.enabled
            else "REFERENCE_DEX_OBSERVATION_NOT_DUE"
        )
        return ReferenceDexObservationTriggerResult(
            triggered=False,
            reason=reason,
            observed_at=observed,
            run=None,
        )
    return await trigger_reference_dex_observation(
        session,
        request=request,
        observed_at=observed,
    )
