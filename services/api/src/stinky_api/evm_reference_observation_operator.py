"""Explicit, auditable operator seam over #249 with durable replay protection."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.evm_reference_observation_runtime_state import (
    ReferenceDexObservationRuntimeState,
    load_reference_observation_runtime_state,
    record_reference_observation_completion,
)
from stinky_api.evm_reference_observation_trigger import (
    ReferenceDexObservationSchedule,
    ReferenceDexObservationTriggerRequest,
    ReferenceDexObservationTriggerResult,
    run_reference_dex_observation_if_due,
)


@dataclass(frozen=True, slots=True)
class DurableReferenceDexObservationResult:
    trigger: ReferenceDexObservationTriggerResult
    state: ReferenceDexObservationRuntimeState | None


async def invoke_reference_dex_observation(
    session: AsyncSession, *, schedule: ReferenceDexObservationSchedule,
    request: ReferenceDexObservationTriggerRequest, now: datetime,
) -> DurableReferenceDexObservationResult:
    """Explicitly invoke one read-only observation using durable completion state."""
    chain = request.pool.chain
    pool_address = request.pool.pool_address
    state = await load_reference_observation_runtime_state(
        session, chain=chain, pool_address=pool_address,
    )
    if state is not None and request.block_number <= state.last_completed_block:
        raise ValueError("duplicate or replayed reference observation block")

    trigger = await run_reference_dex_observation_if_due(
        session, schedule=schedule, request=request, now=now,
        last_completed_at=None if state is None else state.last_completed_at,
    )
    if not trigger.triggered:
        return DurableReferenceDexObservationResult(trigger=trigger, state=state)

    completed = await record_reference_observation_completion(
        session, chain=chain, pool_address=pool_address,
        block_number=request.block_number, completed_at=trigger.observed_at,
    )
    return DurableReferenceDexObservationResult(trigger=trigger, state=completed)
