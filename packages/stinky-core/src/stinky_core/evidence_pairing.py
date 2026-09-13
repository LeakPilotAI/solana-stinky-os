from dataclasses import dataclass

# Pure evidence-only structure. No external calls or state changes.
@dataclass(frozen=True, slots=True)
class PairingEvidence:
    left: str | None
    right: str | None
    verdict: str


def compare_labels(left: str | None, right: str | None) -> PairingEvidence:
    result = "UNKNOWN" if left is None or right is None else ("CONSISTENT" if left == right else "CONFLICT")
    return PairingEvidence(left, right, result)
