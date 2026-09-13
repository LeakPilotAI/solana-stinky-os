"""Router implementation fingerprint evidence composition."""
from __future__ import annotations

from typing import Iterable

from .evm_implementation_registry import (
    ImplementationFingerprintEntry,
    ImplementationFingerprintEvidence,
    classify_implementation_fingerprint,
)
from .evm_router_swap import RouterSwapCallEvidence


def classify_router_implementation(
    evidence: RouterSwapCallEvidence,
    registry: Iterable[ImplementationFingerprintEntry],
) -> ImplementationFingerprintEvidence:
    """Classify the exact historical router code already embedded in call evidence."""
    code = evidence.router_code
    if code.chain != evidence.chain:
        raise ValueError("router code evidence must share router-call chain")
    if code.address != evidence.router:
        raise ValueError("router code evidence address must match router-call target")
    if code.block_number != evidence.block_number:
        raise ValueError("router code evidence must share router-call historical block")
    return classify_implementation_fingerprint(code, registry, expected_role="ROUTER")
