"""Investigation stages. Labels on the existing pipeline. Not a second engine.

DISCOVERY     something unusual is happening (Gate 1 volume)
INVESTIGATION inspect what is causing the activity
RECOGNITION   does this resemble something already observed
CONFIDENCE    how much historical evidence supports that resemblance
OUTCOME       what actually happened afterward (later, never at decision time)

Volume is the discovery trigger. It is not recognition. It is not confidence.
"""

from __future__ import annotations

from typing import Any, Mapping

STAGES_VERSION = "stages-v1.0.0"

STAGE_DISCOVERY = "DISCOVERY"
STAGE_INVESTIGATION = "INVESTIGATION"
STAGE_RECOGNITION = "RECOGNITION"
STAGE_CONFIDENCE = "CONFIDENCE"
STAGE_OUTCOME = "OUTCOME"

STAGES = (
    STAGE_DISCOVERY,
    STAGE_INVESTIGATION,
    STAGE_RECOGNITION,
    STAGE_CONFIDENCE,
    STAGE_OUTCOME,
)


def slice_stage(offset_sec: int) -> str:
    """Map a T+ offset onto a stage. Missing ticks stay UNKNOWN at the caller."""
    n = int(offset_sec or 0)
    if n <= 0:
        return STAGE_DISCOVERY
    if n <= 60:
        return STAGE_INVESTIGATION
    if n <= 180:
        return STAGE_RECOGNITION
    return STAGE_OUTCOME


def _status(*, observed: bool, sample: int | None = None, measured_floor: int = 5) -> str:
    if not observed:
        return "UNKNOWN"
    if sample is None:
        return "OBSERVED"
    if sample < 3:
        return "OBSERVED"
    if sample < measured_floor:
        return "DEVELOPING"
    return "MEASURED"


def investigation_stages(
    *,
    volume_m5_usd: float | None,
    gate1_passed: bool,
    investigation_complete: bool,
    has_intelligence: bool,
    similarity_sample: int | None,
    similarity_confidence: Any,
    outcome_label: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Stage card for one investigation. Outcome is UNKNOWN at decision time."""
    sample = int(similarity_sample or 0)
    conf = similarity_confidence
    conf_unknown = conf in (None, "UNKNOWN", "") or sample < 5
    outcome = (outcome_label or "UNKNOWN").upper()
    # Decision-time never claims a later path.
    decision_outcome = "UNKNOWN"
    return {
        "version": STAGES_VERSION,
        "as_of": as_of,
        "discovery": {
            "stage": STAGE_DISCOVERY,
            "status": "OBSERVED" if gate1_passed and volume_m5_usd is not None else "UNKNOWN",
            "volume_m5_usd": volume_m5_usd,
            "note": "5m volume is the discovery trigger, not evidence the token is good.",
        },
        "investigation": {
            "stage": STAGE_INVESTIGATION,
            "status": "OBSERVED" if investigation_complete else "UNKNOWN",
            "complete": bool(investigation_complete),
            "note": "Inspect wallets, creator, flow, and risk. Missing stays UNKNOWN.",
        },
        "recognition": {
            "stage": STAGE_RECOGNITION,
            "status": _status(observed=sample > 0, sample=sample),
            "sample_count": sample if sample else None,
            "note": "Resemblance needs ≥5 as-of matches and ≥3 informative bands.",
        },
        "confidence": {
            "stage": STAGE_CONFIDENCE,
            "status": "UNKNOWN" if conf_unknown else "MEASURED",
            "similarity_confidence": conf if not conf_unknown else "UNKNOWN",
            "calibrated_probability": False,
            "note": "Not a percent chance of running. SAMPLE SIZE TOO SMALL stays UNKNOWN.",
        },
        "outcome": {
            "stage": STAGE_OUTCOME,
            "status": "UNKNOWN" if decision_outcome == "UNKNOWN" else outcome,
            "decision_time_label": "UNKNOWN",
            "later_label": outcome if outcome != "UNKNOWN" else "UNKNOWN",
            "note": "Outcome belongs to memory/backtest, never to the original decision.",
        },
        "has_intelligence": bool(has_intelligence),
        "calibrated_probability": False,
    }


def stages_from_investigation(inv: Mapping[str, Any] | Any, *, as_of: str | None = None) -> dict[str, Any]:
    sim = getattr(inv, "similarity", None) if not isinstance(inv, Mapping) else inv.get("similarity")
    sim = sim or {}
    activity = getattr(inv, "activity", None) if not isinstance(inv, Mapping) else inv.get("activity")
    vol = None
    if activity is not None:
        vol = activity.volume_m5_usd if hasattr(activity, "volume_m5_usd") else (activity or {}).get("volume_m5_usd")
    return investigation_stages(
        volume_m5_usd=vol,
        gate1_passed=True,
        investigation_complete=bool(getattr(inv, "complete", True) if not isinstance(inv, Mapping) else inv.get("complete", True)),
        has_intelligence=bool(getattr(inv, "has_intelligence", False) if not isinstance(inv, Mapping) else inv.get("has_intelligence")),
        similarity_sample=(sim or {}).get("sample_count"),
        similarity_confidence=(sim or {}).get("similarity_confidence"),
        outcome_label=None,
        as_of=as_of or (getattr(inv, "decision_timestamp", None) if not isinstance(inv, Mapping) else inv.get("decision_timestamp")),
    )
