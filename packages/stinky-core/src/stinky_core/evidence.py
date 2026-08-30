"""Normalized investigation evidence. Provenance required. Missing stays UNKNOWN.

UNKNOWN is insufficient evidence. It is not a positive. It does not promote.

EvidenceItem remains the provenance ledger. EvidenceFinding is the first-class
intelligence finding the desk and UI consume: finding / status / confidence /
evidence_count. Do not duplicate engines — findings are derived from items.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

EVIDENCE_VERSION = "evidence-v1.1.0"

CATEGORIES = (
    "MARKET",
    "FLOW",
    "CREATOR",
    "WALLETS",
    "ENTITY",
    "PATTERN",
    "DATA_QUALITY",
)

FINDING_STATUSES = ("UNKNOWN", "OBSERVED", "DEVELOPING", "MEASURED", "STRONG", "HIGH_RISK", "KNOWN", "MISSING")


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
class EvidenceFinding:
    finding: str
    status: str
    confidence: str | None
    evidence_count: int
    supporting_wallets: int | None = None
    supporting_mints: int | None = None
    observed_at: str | None = None
    as_of: str | None = None
    explanation: str = ""
    category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceBundle:
    items: list[EvidenceItem] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    would_change_conclusion: list[str] = field(default_factory=list)
    promote: bool = False
    insufficient_evidence: bool = True
    findings: list[EvidenceFinding] = field(default_factory=list)
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
            "findings": [f.to_dict() for f in self.findings],
            "finding_count": len(self.findings),
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


def _finding_status(*, observed: bool, sample: int | None = None, measured_floor: int = 8, strong_floor: int = 15, high_risk: bool = False) -> str:
    if high_risk:
        return "HIGH_RISK"
    if not observed:
        return "UNKNOWN"
    n = int(sample or 0)
    if n <= 0:
        return "OBSERVED"
    if n < 3:
        return "OBSERVED"
    if n < measured_floor:
        return "DEVELOPING"
    if n < strong_floor:
        return "MEASURED"
    return "MEASURED"  # STRONG is reserved for documented reputation floors, never auto-promoted here


def finding(
    name: str,
    *,
    status: str,
    explanation: str,
    evidence_count: int = 0,
    confidence: str | None = None,
    supporting_wallets: int | None = None,
    supporting_mints: int | None = None,
    observed_at: str | None = None,
    as_of: str | None = None,
    category: str | None = None,
) -> EvidenceFinding:
    st = status if status in FINDING_STATUSES else "UNKNOWN"
    conf = confidence
    if st in ("UNKNOWN", "MISSING"):
        conf = "UNKNOWN"
        evidence_count = int(evidence_count or 0)
    return EvidenceFinding(
        finding=name,
        status=st,
        confidence=conf if conf is not None else ("UNKNOWN" if st in ("UNKNOWN", "MISSING", "OBSERVED") else st),
        evidence_count=int(evidence_count or 0),
        supporting_wallets=supporting_wallets,
        supporting_mints=supporting_mints,
        observed_at=observed_at,
        as_of=as_of,
        explanation=explanation,
        category=category,
    )


def findings_ledger(
    *,
    volume_m5_usd: float | None = None,
    wallet_status: str | None = None,
    smart_wallet_count: int | None = None,
    wallet_reputation_tier: str | None = None,
    wallet_sample_resolved: int | None = None,
    creator_status: str | None = None,
    creator_launches: int | None = None,
    creator_reputation_tier: str | None = None,
    pattern_kinds: Iterable[str] | None = None,
    similarity_sample: int | None = None,
    similarity_runners: int | None = None,
    similarity_fades: int | None = None,
    entity_link_count: int | None = None,
    synthetic_level: str | None = None,
    rug_level: str | None = None,
    top4_share: float | None = None,
    as_of: str | None = None,
    observed_at: str | None = None,
) -> list[EvidenceFinding]:
    """First-class findings. Never fabricate STRONG. Tiny samples stay OBSERVED/UNKNOWN."""
    out: list[EvidenceFinding] = []
    vol_obs = volume_m5_usd is not None
    out.append(finding(
        "gate1_volume",
        status="OBSERVED" if vol_obs else "UNKNOWN",
        evidence_count=1 if vol_obs else 0,
        explanation=(
            f"${volume_m5_usd:,.0f} 5m volume is the discovery trigger, not a buy."
            if vol_obs else "5m volume UNKNOWN"
        ),
        as_of=as_of, observed_at=observed_at, category="MARKET",
    ))

    w_status = (wallet_status or "UNKNOWN").upper()
    smart = int(smart_wallet_count or 0)
    w_tier = (wallet_reputation_tier or "OBSERVED").upper()
    w_resolved = int(wallet_sample_resolved or 0)
    if w_status == "UNKNOWN" and smart <= 0:
        out.append(finding(
            "wallet_intelligence",
            status="UNKNOWN",
            evidence_count=0,
            explanation="No stored early-wallet track records as-of.",
            as_of=as_of, observed_at=observed_at, category="WALLETS",
        ))
    else:
        st = w_tier if w_tier in FINDING_STATUSES else ("KNOWN" if w_status == "KNOWN" else "OBSERVED")
        if w_resolved <= 2:
            st = "OBSERVED"
        out.append(finding(
            "wallet_intelligence",
            status=st,
            evidence_count=smart if smart else w_resolved,
            supporting_wallets=smart if smart else None,
            confidence=st,
            explanation=(
                f"{smart} measured-edge wallet(s); reputation {st}; resolved sample {w_resolved}."
                if smart else f"Wallets {w_status}; reputation {st}; not smart money."
            ),
            as_of=as_of, observed_at=observed_at, category="WALLETS",
        ))
    if smart >= 1:
        out.append(finding(
            "repeat_early_buyer",
            status="OBSERVED" if w_resolved < 3 else ("DEVELOPING" if w_resolved < 8 else "MEASURED"),
            evidence_count=smart,
            supporting_wallets=smart,
            explanation=f"{smart} wallet(s) previously appeared among early buyers of measured tokens.",
            as_of=as_of, observed_at=observed_at, category="WALLETS",
        ))

    c_status = (creator_status or "UNKNOWN").upper()
    launches = int(creator_launches or 0)
    c_tier = (creator_reputation_tier or "UNKNOWN").upper()
    if c_status == "UNKNOWN" and launches <= 0:
        out.append(finding(
            "creator_intelligence",
            status="UNKNOWN",
            evidence_count=0,
            explanation="Creator history UNKNOWN as-of.",
            as_of=as_of, observed_at=observed_at, category="CREATOR",
        ))
    else:
        st = c_tier if c_tier in FINDING_STATUSES else ("OBSERVED" if launches < 3 else "DEVELOPING")
        out.append(finding(
            "creator_intelligence",
            status=st,
            evidence_count=launches,
            supporting_mints=launches if launches else None,
            confidence=st,
            explanation=f"Creator launches {launches} as-of; reputation {st}. Serial is risk, not confidence.",
            as_of=as_of, observed_at=observed_at, category="CREATOR",
        ))

    kinds = set(pattern_kinds or [])
    if "concentrated_early_book" in kinds or (top4_share is not None and top4_share >= 0.70):
        out.append(finding(
            "concentrated_early_book",
            status="OBSERVED",
            evidence_count=1,
            explanation=f"Top-4 wallet volume share {top4_share if top4_share is not None else 'observed'} ≥ 0.70.",
            as_of=as_of, observed_at=observed_at, category="FLOW",
        ))
    if "co_buy_cluster" in kinds or (entity_link_count or 0) >= 1:
        links = int(entity_link_count or 0)
        out.append(finding(
            "recurring_cobuy_relationship",
            status="OBSERVED" if links < 3 else "DEVELOPING",
            evidence_count=links or 1,
            supporting_wallets=links or None,
            explanation=f"{links} prior co-buy relationship(s) as-of. Neutral wording — not 'insiders'.",
            as_of=as_of, observed_at=observed_at, category="ENTITY",
        ))
    else:
        out.append(finding(
            "recurring_cobuy_relationship",
            status="UNKNOWN",
            evidence_count=0,
            explanation="No prior co-buy relationships as-of.",
            as_of=as_of, observed_at=observed_at, category="ENTITY",
        ))

    sample = int(similarity_sample or 0)
    if sample <= 0:
        out.append(finding(
            "historical_resemblance",
            status="UNKNOWN",
            evidence_count=0,
            explanation="No historical fingerprint matches as-of (need ≥5 and ≥3 informative bands).",
            as_of=as_of, observed_at=observed_at, category="PATTERN",
        ))
    elif sample < 5:
        out.append(finding(
            "historical_resemblance",
            status="OBSERVED",
            evidence_count=sample,
            supporting_mints=sample,
            explanation=f"Fingerprint seen {sample} times as-of; need ≥5 to claim resemblance. Not a probability.",
            as_of=as_of, observed_at=observed_at, category="PATTERN",
        ))
    else:
        out.append(finding(
            "historical_resemblance",
            status="MEASURED",
            evidence_count=sample,
            supporting_mints=sample,
            confidence="MEASURED",
            explanation=(
                f"{sample} comparable tokens as-of: "
                f"{int(similarity_runners or 0)} RUNNER / {int(similarity_fades or 0)} FADE. "
                "Not a percent chance of running."
            ),
            as_of=as_of, observed_at=observed_at, category="PATTERN",
        ))

    syn = (synthetic_level or "UNKNOWN").upper()
    out.append(finding(
        "synthetic_risk",
        status="UNKNOWN" if syn == "UNKNOWN" else ("HIGH_RISK" if syn in ("HIGH", "CRITICAL") else "OBSERVED"),
        evidence_count=0 if syn == "UNKNOWN" else 1,
        explanation=f"Synthetic indicators: {syn}. HIGH needs ≥2 independent families.",
        as_of=as_of, observed_at=observed_at, category="FLOW",
    ))
    rug = (rug_level or "UNKNOWN").upper()
    out.append(finding(
        "rug_risk",
        status="UNKNOWN" if rug == "UNKNOWN" else ("HIGH_RISK" if rug in ("HIGH", "CRITICAL") else "OBSERVED"),
        evidence_count=0 if rug == "UNKNOWN" else 1,
        explanation=f"Rug indicators: {rug}.",
        as_of=as_of, observed_at=observed_at, category="FLOW",
    ))
    return out


def findings_from_bundle(bundle: Mapping[str, Any] | EvidenceBundle) -> list[dict[str, Any]]:
    if isinstance(bundle, EvidenceBundle):
        return [f.to_dict() for f in bundle.findings]
    raw = bundle.get("findings") if isinstance(bundle, Mapping) else None
    if isinstance(raw, list):
        return [dict(x) for x in raw if isinstance(x, Mapping)]
    return []
