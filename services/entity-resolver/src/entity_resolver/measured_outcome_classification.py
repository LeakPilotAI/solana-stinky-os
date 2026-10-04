"""Compatibility re-export for the shared canonical measured-outcome classifier.

The implementation lives in stinky_core so collectors and entity reconciliation use
one deterministic contract. This module remains import-compatible for existing code.
"""
from stinky_core.measured_outcomes import (
    CLASSIFIED_OUTCOMES,
    MAX_HORIZON_EDGE_GAP_SEC,
    classify_completed_market_path,
)

__all__ = [
    "CLASSIFIED_OUTCOMES",
    "MAX_HORIZON_EDGE_GAP_SEC",
    "classify_completed_market_path",
]
