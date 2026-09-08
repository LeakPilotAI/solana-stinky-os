"""Deterministic descriptive outcome classification from measured market paths.

This module reuses the canonical stinky-core outcome contract. It never predicts a
future outcome and never upgrades incomplete evidence. A label is produced only
from snapshots captured during a durably completed observation window; otherwise
UNKNOWN is preserved.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any

from stinky_core.outcomes import (
    DEFAULT_OBSERVATION_WINDOW_SEC,
    FADE,
    HELD,
    RUNNER,
    UNKNOWN,
    label_outcome,
)

CLASSIFIED_OUTCOMES = {RUNNER, HELD, FADE}


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def classify_completed_market_path(
    track: dict[str, Any],
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify one completed track from factual snapshot path statistics.

    The completion boundary supplies observation completeness. The price path supplies
    the canonical peak multiple and maximum peak-to-subsequent drawdown. Missing or
    short observation windows remain UNKNOWN. No current/future decision fields are
    modified by this function.
    """
    migration_at = _dt(track.get("migration_at"))
    completed_at = _dt(track.get("completed_at"))
    if migration_at is None or completed_at is None or completed_at < migration_at:
        return {
            "label": UNKNOWN,
            "reason": "invalid_completion_boundary",
            "evidence_only": True,
        }

    completed_window = (completed_at - migration_at).total_seconds()
    if completed_window + 1e-9 < DEFAULT_OBSERVATION_WINDOW_SEC:
        return {
            "label": UNKNOWN,
            "reason": "incomplete_observation_window",
            "observation_window": completed_window,
            "required_observation_window": DEFAULT_OBSERVATION_WINDOW_SEC,
            "evidence_only": True,
        }

    points: list[tuple[datetime, float, float | None, float | None]] = []
    for row in snapshots or []:
        if not isinstance(row, dict):
            continue
        captured_at = _dt(row.get("captured_at"))
        price = _number(row.get("price_usd"))
        if captured_at is None or price is None or price <= 0:
            continue
        if captured_at < migration_at or captured_at > completed_at:
            continue
        volume = _number(row.get("volume_m5_usd"))
        liquidity = _number(row.get("liquidity_usd"))
        points.append((captured_at, price, volume, liquidity))

    points.sort(key=lambda item: item[0])
    if len(points) < 2:
        return {
            "label": UNKNOWN,
            "reason": "insufficient_measured_price_path",
            "valid_price_snapshot_count": len(points),
            "evidence_only": True,
        }

    first_at, entry_price, entry_volume, entry_liquidity = points[0]
    peak_index = max(range(len(points)), key=lambda idx: points[idx][1])
    peak_at, peak_price, _, _ = points[peak_index]
    final_at, final_price, _, final_liquidity = points[-1]
    peak_multiple = peak_price / entry_price if entry_price > 0 else None

    rolling_peak = points[0][1]
    max_drawdown = 0.0
    max_drawdown_at = points[0][0]
    for captured_at, price, _, _ in points:
        if price > rolling_peak:
            rolling_peak = price
        if rolling_peak > 0:
            drawdown = (rolling_peak - price) / rolling_peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                max_drawdown_at = captured_at

    volumes = [value for _, _, value, _ in points if value is not None and value >= 0]
    peak_volume = max(volumes) if volumes else None
    liquidity_values = [value for _, _, _, value in points if value is not None and value >= 0]
    liquidity_drop = None
    if entry_liquidity is not None and entry_liquidity > 0 and liquidity_values:
        minimum_liquidity = min(liquidity_values)
        liquidity_drop = max(0.0, (entry_liquidity - minimum_liquidity) / entry_liquidity)

    outcome = label_outcome(
        peak_multiple=peak_multiple,
        peak_volume=peak_volume,
        entry_volume=entry_volume,
        entry_price=entry_price,
        decision_timestamp=migration_at.isoformat(),
        drawdown=max_drawdown,
        time_to_peak=(peak_at - migration_at).total_seconds(),
        time_to_drawdown=(max_drawdown_at - migration_at).total_seconds(),
        observation_window=completed_window,
        observation_complete=True,
        liquidity_drop=liquidity_drop,
    )

    evidence = outcome.to_dict()
    evidence.update(
        {
            "evidence_basis": "completed_market_snapshot_path",
            "source_table": "market_snapshots",
            "migration_at": migration_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "first_snapshot_at": first_at.isoformat(),
            "final_snapshot_at": final_at.isoformat(),
            "valid_price_snapshot_count": len(points),
            "entry_price_usd": entry_price,
            "peak_price_usd": peak_price,
            "final_price_usd": final_price,
            "final_liquidity_usd": final_liquidity,
            "canonical_classification": True,
            "evidence_only": True,
            "predictive_authority": False,
            "trade_signal": False,
        }
    )
    return evidence
