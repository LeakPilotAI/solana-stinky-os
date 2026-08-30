"""Normalized investigation evidence. Provenance required. Missing stays UNKNOWN.

UNKNOWN is insufficient evidence. It is not a positive. It does not promote.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

EVIDENCE_VERSION = "evidence-v1.0.0"

CATEGORIES = (
    "MARKET",
    "FLOW",
    "CREATOR",
    "WALLETS",
    "ENTITY",
    "PATTERN",
    "DATA_QUALITY",
)


@dataclass
class EvidenceItem:
    category: str
    signal: str
    value: Any
    status: str  # OBSERVED | KNOWN | UNKNOWN | MISSING
    confidence: float | None
    source: str
    explanation: str
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceBundle:
    items: list[EvidenceItem] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    would_change_conclusion: list[str] = field(default_factory=list)
    promote: bool = False
    insufficient_evidence: bool = True
    model_version: str = EVIDENCE_VERSION

    def add(self, item: EvidenceItem) -> None:
        self.items.append(item)
        if item.status in ("UNKNOWN", "MISSING"):
            key = f"{item.category}:{item.signal}"
            if key not in self.missing:
                self.missing.append(key)

    def to_dict(self) -> dict[str, Any]:
        by_cat: dict[str, list[dict[str, Any]]] = {c: [] for c in CATEGORIES}
        for it in self.items:
            by_cat.setdefault(it.category, []).append(it.to_dict())
        return {
            "by_category": by_cat,
            "missing": list(self.missing),
            "would_change_conclusion": list(self.would_change_conclusion),
            "promote": self.promote,
            "insufficient_evidence": self.insufficient_evidence,
            "model_version": self.model_version,
            "item_count": len(self.items),
        }


def item(
    category: str,
    signal: str,
    value: Any,
    *,
    status: str,
    source: str,
    explanation: str,
    confidence: float | None = None,
    provenance: dict[str, Any] | None = None,
) -> EvidenceItem:
    st = status if value is not None or status in ("UNKNOWN", "MISSING") else "MISSING"
    if value is None and st == "OBSERVED":
        st = "MISSING"
    return EvidenceItem(
        category=category,
        signal=signal,
        value=value,
        status=st,
        confidence=confidence,
        source=source,
        explanation=explanation,
        provenance=provenance or {"source": source},
    )
