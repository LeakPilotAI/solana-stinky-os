from dataclasses import dataclass

# Pure evidence-only structure. No external calls or state changes.
@dataclass(frozen=True, slots=True)
class PairingEvidence:
    left: str | None
    right: str | None
    verdict: str
