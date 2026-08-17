"""Versioned feature definitions (ADR-006).

Feature Definition Version + Feature Set Version are stored with every
materialized feature vector so historical predictions remain reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    """A single named feature with extraction logic and metadata."""

    name: str
    description: str
    dtype: str  # float, int, bool, str, dict
    version: str  # feature definition version
    extractor: Callable[[dict[str, Any]], Any]


# ---------------------------------------------------------------------------
# Feature set v1.0.0 – basic launch / entity features
# Deterministic only. No ML. Fully explainable.
# ---------------------------------------------------------------------------

FEATURE_DEF_VERSION = "1.0.0"
FEATURE_SET_HASH = "fs-v1.0.0-launch-basic"


def _get(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in payload:
            return payload[k]
    return default


def extract_launch_count(ctx: dict[str, Any]) -> int:
    return int(_get(ctx, "launch_count", default=0))


def extract_bond_rate(ctx: dict[str, Any]) -> float:
    launches = int(_get(ctx, "launch_count", default=0))
    bonded = int(_get(ctx, "bonded_count", default=0))
    if launches == 0:
        return 0.0
    return round(bonded / launches, 4)


def extract_median_ath_multiple(ctx: dict[str, Any]) -> float:
    return float(_get(ctx, "median_ath_multiple", default=0.0))


def extract_rug_count(ctx: dict[str, Any]) -> int:
    return int(_get(ctx, "rug_count", default=0))


def extract_wallet_age_days(ctx: dict[str, Any]) -> float:
    return float(_get(ctx, "wallet_age_days", default=0.0))


def extract_unique_funding_sources(ctx: dict[str, Any]) -> int:
    return int(_get(ctx, "unique_funding_sources", default=0))


def extract_repeat_buyer_ratio(ctx: dict[str, Any]) -> float:
    return float(_get(ctx, "repeat_buyer_ratio", default=0.0))


def extract_has_rug_history(ctx: dict[str, Any]) -> bool:
    return bool(_get(ctx, "rug_count", default=0) > 0)


FEATURE_DEFINITIONS: list[FeatureDefinition] = [
    FeatureDefinition(
        name="launch_count",
        description="Total historical token launches by this entity",
        dtype="int",
        version=FEATURE_DEF_VERSION,
        extractor=extract_launch_count,
    ),
    FeatureDefinition(
        name="bond_rate",
        description="Fraction of launches that successfully bonded",
        dtype="float",
        version=FEATURE_DEF_VERSION,
        extractor=extract_bond_rate,
    ),
    FeatureDefinition(
        name="median_ath_multiple",
        description="Median ATH multiple across historical launches",
        dtype="float",
        version=FEATURE_DEF_VERSION,
        extractor=extract_median_ath_multiple,
    ),
    FeatureDefinition(
        name="rug_count",
        description="Number of launches classified as rugs",
        dtype="int",
        version=FEATURE_DEF_VERSION,
        extractor=extract_rug_count,
    ),
    FeatureDefinition(
        name="wallet_age_days",
        description="Age of the primary wallet in days",
        dtype="float",
        version=FEATURE_DEF_VERSION,
        extractor=extract_wallet_age_days,
    ),
    FeatureDefinition(
        name="unique_funding_sources",
        description="Distinct wallets that have funded this entity",
        dtype="int",
        version=FEATURE_DEF_VERSION,
        extractor=extract_unique_funding_sources,
    ),
    FeatureDefinition(
        name="repeat_buyer_ratio",
        description="Share of holders who bought more than one launch",
        dtype="float",
        version=FEATURE_DEF_VERSION,
        extractor=extract_repeat_buyer_ratio,
    ),
    FeatureDefinition(
        name="has_rug_history",
        description="Whether the entity has any prior rug",
        dtype="bool",
        version=FEATURE_DEF_VERSION,
        extractor=extract_has_rug_history,
    ),
]


def compute_feature_vector(context: dict[str, Any]) -> dict[str, Any]:
    """Compute the full feature vector for the current feature set."""
    values: dict[str, Any] = {}
    for fd in FEATURE_DEFINITIONS:
        values[fd.name] = fd.extractor(context)
    return values
