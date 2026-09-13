from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class PairingEvidence:
    left: str | None
    right: str | None
    verdict: str
