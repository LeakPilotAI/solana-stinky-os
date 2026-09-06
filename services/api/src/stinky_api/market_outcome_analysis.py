"""Build comparable descriptive market-path signatures from observed evidence."""

from __future__ import annotations

import math
from typing import Any


METRIC_KEYS = (
    "price_usd",
    "liquidity_usd",
    "volume_5m_usd",
    "volume_usd",
    "fdv_usd",
    "market_cap_usd",
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _pct_change(first: float, last: float) -> float | None:
    if first == 0:
        return None
    return ((last - first) / abs(first)) * 100.0


def _metric_summary(values: list[tuple[str, float]]) -> dict[str, Any]:
    first_horizon, first_value = values[0]
    last_horizon, last_value = values[-1]
    max_horizon, max_value = max(values, key=lambda item: item[1])
    min_horizon, min_value = min(values, key=lambda item: item[1])
    return {
        "first": {"horizon": first_horizon, "value": first_value},
        "last": {"horizon": last_horizon, "value": last_value},
        "min": {"horizon": min_horizon, "value": min_value},
        "max": {"horizon": max_horizon, "value": max_value},
        "percent_change_first_to_last": _pct_change(first_value, last_value),
        "observations": len(values),
    }


def analyze_market_lifecycle(records: list[dict[str, Any]], *, limit: int = 100) -> dict[str, Any]:
    """Return factual path/extreme measurements from observed lifecycle records."""
    bounded_limit = max(1, min(int(limit), 500))
    bounded_records = [r for r in records[:bounded_limit] if isinstance(r, dict)]
    if not bounded_records:
        return {
            "status": "UNKNOWN",
            "observed_horizons": [],
            "observed_record_count": 0,
            "metrics": {},
            "missing": ["market_outcome_observations"],
            "bounded": {"limit": bounded_limit},
            "evidence_only": True,
        }

    horizons = [str(r.get("horizon")) for r in bounded_records if r.get("horizon")]
    metrics_out: dict[str, Any] = {}
    for key in METRIC_KEYS:
        values: list[tuple[str, float]] = []
        for record in bounded_records:
            metrics = record.get("metrics")
            if not isinstance(metrics, dict):
                continue
            value = _number(metrics.get(key))
            horizon = record.get("horizon")
            if value is not None and horizon:
                values.append((str(horizon), value))
        if values:
            metrics_out[key] = _metric_summary(values)

    return {
        "status": "OBSERVED",
        "observed_horizons": horizons,
        "observed_record_count": len(bounded_records),
        "metrics": metrics_out,
        "missing": [],
        "bounded": {"limit": bounded_limit},
        "evidence_basis": "market_snapshot_observation",
        "evidence_only": True,
    }


def market_path_signature(analysis: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic, outcome-agnostic descriptor for cross-market comparison.

    The signature uses only observed coverage and structural market-path facts.
    It is not a prediction target, quality score, risk score, or trading signal.
    """
    if not isinstance(analysis, dict) or analysis.get("status") != "OBSERVED":
        return {"status": "UNKNOWN", "signature": {}, "evidence_only": True}

    signature: dict[str, Any] = {
        "observed_horizons": list(analysis.get("observed_horizons", [])),
        "observed_record_count": int(analysis.get("observed_record_count", 0)),
        "metrics": {},
    }
    metrics = analysis.get("metrics")
    if isinstance(metrics, dict):
        for key in METRIC_KEYS:
            item = metrics.get(key)
            if not isinstance(item, dict):
                continue
            signature["metrics"][key] = {
                "observations": item.get("observations"),
                "first_horizon": item.get("first", {}).get("horizon") if isinstance(item.get("first"), dict) else None,
                "last_horizon": item.get("last", {}).get("horizon") if isinstance(item.get("last"), dict) else None,
                "percent_change_first_to_last": item.get("percent_change_first_to_last"),
            }

    return {"status": "OBSERVED", "signature": signature, "evidence_only": True}
