"""Progressive intelligence after Gate 1. Deterministic, evidence-only.

Volume gets a CA onto the desk. This module decides whether it deserves attention.
Never fabricates historical similarity, fees, wallets, or scores.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from time import perf_counter
from typing import Any, Mapping

from stinky_core.inspect import (
    INSPECT_VERSION,
    Evidence,
    MarketActivity,
    RiskResult,
    activity_from_trades,
    assess_rug,
    assess_synthetic,
    market_activity_from_mapping,
)
from stinky_core.pools import is_rankable_wallet
from stinky_core.evidence import EvidenceBundle, item as eitem
from stinky_core.fingerprint import book_fingerprint, fingerprint_features
from stinky_core.memory import IntelligenceMemory
from stinky_core.metrics import ENGINE_METRICS
from stinky_core.reputation import creator_reputation, wallet_reputation
from stinky_core.similarity import historical_similarity

INTEL_VERSION = "intel-v1.6.0-recognition"
SCORE_VERSION = "score-v1.1.0-intel-not-volume"
RUNNER_VERSION = "runner-potential-v1.1.0-intel-not-volume"

MARKET_INSPECTIONS_DDL = """
CREATE TABLE IF NOT EXISTS market_inspections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mint TEXT NOT NULL,
    inspected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    model_version TEXT NOT NULL,
    pipeline_status TEXT NOT NULL,
    gate1_passed BOOLEAN NOT NULL DEFAULT TRUE,
    volume_m5_usd DOUBLE PRECISION,
    synthetic_score DOUBLE PRECISION,
    synthetic_level TEXT,
    rug_score DOUBLE PRECISION,
    rug_level TEXT,
    stinky_score DOUBLE PRECISION,
    runner_potential DOUBLE PRECISION,
    score_confidence DOUBLE PRECISION,
    fee_status TEXT,
    global_fees_sol DOUBLE PRECISION,
    has_intelligence BOOLEAN,
    evidence JSONB,
    missing_data JSONB,
    alert_ok BOOLEAN,
    alert_reason TEXT
)
"""
MARKET_INSPECTIONS_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_market_inspections_mint_time ON market_inspections (mint, inspected_at DESC)",
)
MARKET_INSPECTIONS_INSERT = """
INSERT INTO market_inspections (
    mint, model_version, pipeline_status, gate1_passed, volume_m5_usd,
    synthetic_score, synthetic_level, rug_score, rug_level,
    stinky_score, runner_potential, score_confidence,
    fee_status, global_fees_sol, has_intelligence,
    evidence, missing_data, alert_ok, alert_reason
) VALUES (
    :mint, :model_version, :pipeline_status, :gate1_passed, :volume_m5_usd,
    :synthetic_score, :synthetic_level, :rug_score, :rug_level,
    :stinky_score, :runner_potential, :score_confidence,
    :fee_status, :global_fees_sol, :has_intelligence,
    CAST(:evidence AS jsonb), CAST(:missing_data AS jsonb), :alert_ok, :alert_reason
)
"""

STATUS_REJECTED = "REJECTED"
STATUS_DISCOVERED = "DISCOVERED"
STATUS_INVESTIGATING = "INVESTIGATING"
STATUS_QUALIFIED = "QUALIFIED"
STATUS_HIGH_RISK = "HIGH_RISK"
STATUS_ALERT = "ALERT"
STATUS_UNKNOWN = "UNKNOWN"


def _f(v: Any) -> float | None:
    if v is None or v is True or v is False:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def _i(v: Any) -> int | None:
    if v is None or v is True or v is False:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


@dataclass
class CreatorProfile:
    status: str  # KNOWN | OBSERVED | UNKNOWN
    launches: int | None = None
    migrated: int | None = None
    historical_runners: int | None = None
    historical_fades: int | None = None
    historical_unknown: int | None = None
    median_peak_multiple: float | None = None
    linked_wallets: int | None = None
    serial_risk: str | None = None
    entity_id: str | None = None
    confidence: float | None = None
    success_rate: float | None = None
    median_seconds_between_launches: float | None = None
    recurring_buyers: int | None = None
    first_seen: str | None = None
    last_seen: str | None = None
    reputation: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WalletIntel:
    status: str
    early_buyer_count: int | None = None
    meaningful_buyer_count: int | None = None
    unique_wallets: int | None = None
    smart_wallet_count: int | None = None
    avg_hit_rate: float | None = None
    avg_return_pct: float | None = None
    unknown_wallet_count: int | None = None
    winner_count: int | None = None
    loser_count: int | None = None
    reputation: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PatternResult:
    matches: list[dict[str, Any]]
    pattern_confidence: str  # numeric 0-1 string or UNKNOWN
    confidence_value: float | None
    evidence: list[dict[str, Any]]
    missing: list[str] = field(default_factory=list)
    resemblance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_matches": self.matches,
            "pattern_confidence": self.pattern_confidence,
            "confidence_value": self.confidence_value,
            "pattern_evidence": self.evidence,
            "missing": list(self.missing),
            "resemblance": dict(self.resemblance),
        }


@dataclass
class RunnerPotential:
    score: float | None
    confidence: float | None
    positive: list[dict[str, Any]]
    negative: list[dict[str, Any]]
    missing: list[str]
    model_version: str = RUNNER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "runner_potential_score": self.score,
            "confidence": self.confidence,
            "positive_factors": self.positive,
            "negative_factors": self.negative,
            "missing_data": list(self.missing),
            "model_version": self.model_version,
            "calibrated_probability": False,
        }


@dataclass
class ScoreBreakdown:
    score: float
    confidence: float
    positive: list[dict[str, Any]]
    negative: list[dict[str, Any]]
    missing: list[str]
    components: dict[str, float] = field(default_factory=dict)
    model_version: str = SCORE_VERSION
    promotable: bool = False
    actionable: bool = False
    interpretation: str = "INSUFFICIENT_EVIDENCE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "stinky_score": self.score,
            "confidence": self.confidence,
            "positive": self.positive,
            "negative": self.negative,
            "missing_data": list(self.missing),
            "components": dict(self.components),
            "model_version": self.model_version,
            "calibrated_probability": False,
            "promotable": self.promotable,
            "actionable": self.actionable,
            "interpretation": self.interpretation,
        }


@dataclass
class Investigation:
    mint: str | None
    complete: bool
    pipeline_status: str
    activity: MarketActivity
    synthetic: RiskResult
    rug: RiskResult
    creator: CreatorProfile
    wallets: WalletIntel
    patterns: PatternResult
    runner: RunnerPotential
    score: ScoreBreakdown
    fee_status: str
    global_fees_sol: float | None
    has_intelligence: bool
    missing_data: list[str]
    promote: bool = False
    insufficient_evidence: bool = True
    would_change: list[str] = field(default_factory=list)
    entities: dict[str, Any] = field(default_factory=dict)
    fingerprint: str | None = None
    fingerprint_features: dict[str, Any] = field(default_factory=dict)
    decision_timestamp: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    data_quality: dict[str, Any] = field(default_factory=dict)
    why: dict[str, Any] = field(default_factory=dict)
    information_advantage: dict[str, Any] = field(default_factory=dict)
    similarity: dict[str, Any] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)
    model_version: str = INTEL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "mint": self.mint,
            "complete": self.complete,
            "pipeline_status": self.pipeline_status,
            "activity": self.activity.to_dict(),
            "synthetic": self.synthetic.to_dict(),
            "rug": self.rug.to_dict(),
            "creator": self.creator.to_dict(),
            "wallets": self.wallets.to_dict(),
            "patterns": self.patterns.to_dict(),
            "runner": self.runner.to_dict(),
            "score": self.score.to_dict(),
            "fee_status": self.fee_status,
            "global_fees_sol": self.global_fees_sol,
            "has_intelligence": self.has_intelligence,
            "missing_data": list(self.missing_data),
            "promote": self.promote,
            "insufficient_evidence": self.insufficient_evidence,
            "would_change_conclusion": list(self.would_change),
            "entities": dict(self.entities),
            "fingerprint": self.fingerprint,
            "fingerprint_features": dict(self.fingerprint_features),
            "decision_timestamp": self.decision_timestamp,
            "evidence": dict(self.evidence),
            "data_quality": dict(self.data_quality),
            "why": dict(self.why),
            "information_advantage": dict(self.information_advantage),
            "similarity": dict(self.similarity),
            "report": dict(self.report),
            "model_version": self.model_version,
            "inspect_version": INSPECT_VERSION,
            "score_interpretation": self.score.interpretation,
            "score_actionable": self.score.actionable,
            "unknown_not_bullish": True,
        }


def build_creator_profile(raw: Mapping[str, Any] | None) -> CreatorProfile:
    if not raw:
        return CreatorProfile(status="UNKNOWN", missing=["creator_store"], reputation=creator_reputation(launches=0))
    launches = _i(raw.get("launch_count") if raw.get("launch_count") is not None else raw.get("launches"))
    if launches is None and raw.get("entity_id") is None and not raw.get("known"):
        return CreatorProfile(status="UNKNOWN", missing=["creator_store"], reputation=creator_reputation(launches=0))
    runners = _i(raw.get("historical_runners") if raw.get("historical_runners") is not None else raw.get("runners"))
    fades = _i(raw.get("historical_fades") if raw.get("historical_fades") is not None else raw.get("fades"))
    serial = None
    if launches is not None:
        serial = "HIGH" if launches >= 40 else "MEDIUM" if launches >= 15 else "LOW"
    missing = []
    if runners is None:
        missing.append("historical_runners")
    if launches is None or launches < 3:
        status = "OBSERVED"
        missing.append("creator_sample")
        conf = 0.2
    else:
        status = "KNOWN"
        conf = round(min(0.8, 0.3 + 0.04 * launches), 2)
    rep = creator_reputation(
        launches=launches,
        runners=runners,
        fades=fades,
        held=_i(raw.get("historical_held")),
        success_rate=_f(raw.get("success_rate")),
        observation_window=str(raw["as_of"]) if raw.get("as_of") else None,
    )
    return CreatorProfile(
        status=status,
        launches=launches,
        migrated=_i(raw.get("migrated") if raw.get("migrated") is not None else raw.get("migration_count")),
        historical_runners=runners,
        historical_fades=fades,
        historical_unknown=_i(raw.get("historical_unknown")),
        median_peak_multiple=_f(raw.get("median_peak_multiple")),
        linked_wallets=_i(raw.get("wallet_count") if raw.get("wallet_count") is not None else raw.get("linked_wallets")),
        serial_risk=serial,
        entity_id=str(raw["entity_id"]) if raw.get("entity_id") else None,
        confidence=conf,
        success_rate=_f(raw.get("success_rate")),
        median_seconds_between_launches=_f(raw.get("median_seconds_between_launches")),
        recurring_buyers=_i(raw.get("recurring_buyers")),
        first_seen=str(raw["first_seen"]) if raw.get("first_seen") else None,
        last_seen=str(raw["last_seen"]) if raw.get("last_seen") else None,
        reputation=rep,
        missing=missing,
    )


def analyze_wallets(
    buyers: list[Mapping[str, Any]] | None,
    performance: Mapping[str, Mapping[str, Any]] | None = None,
) -> WalletIntel:
    if not buyers:
        return WalletIntel(status="UNKNOWN", missing=["early_buyers"], reputation=wallet_reputation(sample_size=0, sample_resolved=0))
    perf = performance or {}
    meaningful = 0
    smart = 0
    unknown = 0
    winners = 0
    losers = 0
    hit: list[float] = []
    ret: list[float] = []
    wallets = []
    dropped_pool = 0
    for b in buyers:
        w = str(b.get("wallet") or b.get("userAddress") or "").strip()
        if not w:
            continue
        if not is_rankable_wallet(w):
            dropped_pool += 1
            continue
        wallets.append(w)
        spent = _f(b.get("sol_spent") if b.get("sol_spent") is not None else b.get("amountSol"))
        if spent is not None and spent >= 0.05:
            meaningful += 1
        p = perf.get(w)
        if not p:
            unknown += 1
            continue
        early = _i(p.get("early_buy_count")) or 0
        tokens = _i(p.get("tokens_purchased")) or 0
        # Insufficient history is not smart money. Observations without
        # resolved outcomes are not measured edge.
        resolved = _i(p.get("sample_resolved"))
        hr = _f(p.get("hit_rate"))
        if early >= 3 and tokens >= 3:
            if resolved is not None and resolved < 3:
                unknown += 1
                continue
            if resolved is None and hr is None and _i(p.get("runners")) is None:
                unknown += 1
                continue
            smart += 1
            if hr is not None:
                hit.append(hr)
                if hr + 1e-9 >= 0.5:
                    winners += 1
                else:
                    losers += 1
            else:
                rn = _i(p.get("runners")) or 0
                fd = _i(p.get("fades")) or 0
                if rn > fd:
                    winners += 1
                elif fd > rn:
                    losers += 1
            ar = _f(p.get("avg_return_pct"))
            if ar is not None:
                ret.append(ar)
        else:
            unknown += 1
    if not wallets:
        missing = ["early_buyers"]
        if dropped_pool:
            missing.append("pool_wallets_excluded")
        return WalletIntel(status="UNKNOWN", missing=missing)
    evidence = []
    if smart:
        evidence.append({
            "signal": "prior_edge_wallets",
            "value": smart,
            "sample_min": 3,
            "explanation": f"{smart} early wallets have stored track records (sample ≥ 3)",
        })
    status = "KNOWN" if smart else "OBSERVED"
    missing = []
    if unknown:
        missing.append("wallet_history")
    # Aggregate reputation from the strongest measured wallet; tiny samples stay OBSERVED.
    best = wallet_reputation(sample_size=len(wallets), sample_resolved=0)
    for p in (perf or {}).values():
        r = p.get("reputation") if isinstance(p, Mapping) else None
        if not isinstance(r, Mapping):
            r = wallet_reputation(
                sample_size=_i(p.get("sample_size") if isinstance(p, Mapping) else None),
                sample_resolved=_i(p.get("sample_resolved") if isinstance(p, Mapping) else None),
                runners=_i(p.get("runners") if isinstance(p, Mapping) else None),
                fades=_i(p.get("fades") if isinstance(p, Mapping) else None),
                held=_i(p.get("held") if isinstance(p, Mapping) else None),
                hit_rate=_f(p.get("hit_rate") if isinstance(p, Mapping) else None),
            )
        order = {"OBSERVED": 0, "DEVELOPING": 1, "MEASURED": 2, "STRONG": 3}
        if order.get(str(r.get("tier")), 0) > order.get(str(best.get("tier")), 0):
            best = dict(r)
    return WalletIntel(
        status=status,
        early_buyer_count=len(wallets),
        meaningful_buyer_count=meaningful,
        unique_wallets=len(set(wallets)),
        smart_wallet_count=smart,
        avg_hit_rate=(sum(hit) / len(hit)) if hit else None,
        avg_return_pct=(sum(ret) / len(ret)) if ret else None,
        unknown_wallet_count=unknown,
        winner_count=winners,
        loser_count=losers,
        reputation=best,
        evidence=evidence,
        missing=missing,
    )


def match_patterns(
    *,
    wallets: WalletIntel,
    creator: CreatorProfile,
    activity: MarketActivity,
    historical: Mapping[str, Any] | None = None,
) -> PatternResult:
    matches: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    missing: list[str] = []

    if wallets.status in ("KNOWN", "OBSERVED") and (wallets.meaningful_buyer_count or 0) >= 8:
        matches.append({"kind": "dense_early_book", "confidence": 0.7})
        evidence.append({"kind": "dense_early_book", "value": wallets.meaningful_buyer_count})
    if wallets.status == "KNOWN" and (wallets.smart_wallet_count or 0) >= 3:
        matches.append({"kind": "measured_edge", "confidence": 0.65})
        evidence.append({"kind": "measured_edge", "value": wallets.smart_wallet_count, "sample_min": 3})
    if wallets.status == "KNOWN" and (wallets.smart_wallet_count or 0) >= 1:
        matches.append({"kind": "repeat_early_buyer", "confidence": 0.55})
        evidence.append({"kind": "repeat_early_buyer", "value": wallets.smart_wallet_count})
    if creator.status == "KNOWN" and (creator.launches or 0) >= 8:
        matches.append({"kind": "serial_deployer", "confidence": 0.7})
        evidence.append({"kind": "serial_deployer", "value": creator.launches})
    if activity.unique_wallets is not None and activity.unique_wallets >= 6 and (activity.top4_wallet_volume_share or 1) < 0.55:
        matches.append({"kind": "co_buy_cluster", "confidence": 0.4})
        evidence.append({"kind": "co_buy_cluster", "value": activity.unique_wallets})
    if activity.top4_wallet_volume_share is not None and activity.top4_wallet_volume_share >= 0.70:
        matches.append({"kind": "concentrated_early_book", "confidence": 0.6})
        evidence.append({"kind": "concentrated_early_book", "value": activity.top4_wallet_volume_share})

    hist = historical or {}
    resemble = _i(hist.get("similar_runner_count"))
    sample = _i(hist.get("sample_count"))
    resemblance = {
        "sample_count": sample,
        "runner_matches": _i(hist.get("runner_matches")),
        "held_matches": _i(hist.get("held_matches")),
        "fade_matches": _i(hist.get("fade_matches")),
        "unknown_matches": _i(hist.get("unknown_matches")),
        "matching_historical_mints": list(hist.get("matching_historical_mints") or []),
        "pattern_support": dict(hist.get("pattern_support") or {}),
        "runner_pattern": bool(hist.get("runner_pattern")),
        "fade_pattern": bool(hist.get("fade_pattern")),
        "confidence": hist.get("confidence", "UNKNOWN"),
        "calibrated_probability": False,
    }
    if resemble is None:
        missing.append("historical_similarity")
        hist_val = None
    elif sample is not None and sample < 5:
        missing.append("historical_similarity_sample")
        hist_val = None
        evidence.append({
            "kind": "historical_resemblance_insufficient",
            "value": sample,
            "explanation": f"Fingerprint seen {sample} times as-of; need ≥5 to claim resemblance",
        })
    else:
        hist_val = min(1.0, 0.15 + 0.04 * (resemble or 0))
        rn = _i(hist.get("runner_matches")) or 0
        fd = _i(hist.get("fade_matches")) or 0
        hd = _i(hist.get("held_matches")) or 0
        un = _i(hist.get("unknown_matches")) or 0
        evidence.append({
            "kind": "historical_resemblance",
            "value": resemble,
            "explanation": (
                f"Resembles {sample} stored tokens as-of: "
                f"{rn} RUNNER / {hd} HELD / {fd} FADE / {un} UNKNOWN (not a probability)"
            ),
        })
        if hist.get("runner_pattern"):
            matches.append({"kind": "historical_resemblance", "family": "runner_support", "confidence": hist_val, "sample": sample})
        if hist.get("fade_pattern"):
            matches.append({"kind": "historical_failure_resemblance", "family": "fade_support", "confidence": hist_val, "sample": sample})

    if wallets.status == "UNKNOWN" and creator.status == "UNKNOWN":
        missing.append("pattern_inputs")
        return PatternResult(matches=[], pattern_confidence="UNKNOWN", confidence_value=None, evidence=evidence, missing=missing, resemblance=resemblance)

    conf = min(1.0, 0.2 + 0.15 * len(matches))
    if hist_val is None and not matches:
        return PatternResult(matches=[], pattern_confidence="UNKNOWN", confidence_value=None, evidence=evidence, missing=missing, resemblance=resemblance)
    return PatternResult(
        matches=matches,
        pattern_confidence=str(round(conf, 2)),
        confidence_value=round(conf, 2),
        evidence=evidence,
        missing=missing,
        resemblance=resemblance,
    )


def runner_potential(
    *,
    activity: MarketActivity,
    synthetic: RiskResult,
    rug: RiskResult,
    wallets: WalletIntel,
    creator: CreatorProfile,
    patterns: PatternResult,
    volume_gate: float = 150_000.0,
) -> RunnerPotential:
    pos: list[dict[str, Any]] = []
    neg: list[dict[str, Any]] = []
    missing: list[str] = []
    score = 50.0
    used = 0

    # Volume already admitted the CA at Gate 1. It is not a runner signal.
    if activity.volume_m5_usd is None:
        missing.append("volume_m5")

    if wallets.status == "UNKNOWN":
        missing.append("wallets")
    else:
        used += 1
        sw = wallets.smart_wallet_count or 0
        mb = wallets.meaningful_buyer_count or 0
        if sw >= 3:
            score += 10
            pos.append({"delta": 10, "reason": f"{sw} wallets with measured edge (sample ≥ 3)"})
        elif sw >= 1:
            score += 6
            pos.append({"delta": 6, "reason": f"{sw} wallet(s) with measured edge (sample ≥ 3)"})
        elif mb >= 3:
            score -= 4
            neg.append({"delta": -4, "reason": "Meaningful capital without prior-edge wallets"})

    if creator.status == "UNKNOWN":
        missing.append("creator")
    elif creator.status == "OBSERVED":
        missing.append("creator_sample")
        used += 1
        if creator.serial_risk == "HIGH":
            score -= 10
            neg.append({"delta": -10, "reason": "Serial deployer risk HIGH"})
    else:
        used += 1
        if (creator.historical_runners or 0) >= 3 and (creator.launches or 0) >= 5:
            score += 8
            pos.append({"delta": 8, "reason": "Creator has stored runners (sample ≥ 5 launches)"})
        if creator.serial_risk == "HIGH":
            score -= 10
            neg.append({"delta": -10, "reason": "Serial deployer risk HIGH"})

    if synthetic.level == "UNKNOWN":
        missing.append("synthetic")
    else:
        used += 1
        if synthetic.level == "CRITICAL":
            score -= 22
            neg.append({"delta": -22, "reason": "Synthetic risk CRITICAL"})
        elif synthetic.level == "HIGH":
            score -= 12
            neg.append({"delta": -12, "reason": "Synthetic risk HIGH"})
        elif synthetic.level == "LOW":
            score += 4
            pos.append({"delta": 4, "reason": "Synthetic risk LOW on observed flow"})

    if rug.level == "UNKNOWN":
        missing.append("rug")
    elif rug.level in ("HIGH", "CRITICAL"):
        used += 1
        score -= 14 if rug.level == "HIGH" else 22
        neg.append({"delta": -14 if rug.level == "HIGH" else -22, "reason": f"Rug risk {rug.level}"})

    if patterns.pattern_confidence == "UNKNOWN" and not patterns.matches:
        missing.append("patterns")
    elif patterns.matches:
        kinds = {m.get("kind") for m in patterns.matches}
        intel_kinds = kinds & {"measured_edge", "historical_resemblance", "repeat_early_buyer"}
        if intel_kinds:
            used += 1
            score += 6
            pos.append({"delta": 6, "reason": "Historical/edge pattern match (not volume)"})
        elif "dense_early_book" in kinds or "co_buy_cluster" in kinds:
            missing.append("pattern_history")

    if used == 0:
        return RunnerPotential(score=None, confidence=None, positive=pos, negative=neg, missing=missing)
    conf = max(0.15, min(0.9, 0.25 + 0.12 * used - 0.08 * len(missing)))
    return RunnerPotential(
        score=round(max(0.0, min(100.0, score)), 1),
        confidence=round(conf, 2),
        positive=pos,
        negative=neg,
        missing=missing,
    )


def compose_stinky_score(
    *,
    activity: MarketActivity,
    synthetic: RiskResult,
    rug: RiskResult,
    wallets: WalletIntel,
    creator: CreatorProfile,
    patterns: PatternResult,
    runner: RunnerPotential,
    fee_status: str,
    global_fees_sol: float | None,
    volume_gate: float = 150_000.0,
    entity_link_count: int = 0,
) -> ScoreBreakdown:
    """Volume is the investigation trigger, not the score. No ML calibration."""
    pos: list[dict[str, Any]] = []
    neg: list[dict[str, Any]] = []
    missing: list[str] = []
    score = 50.0
    conf = 0.35
    components: dict[str, float] = {
        "base_score": 50.0,
        "volume_component": 0.0,
        "wallet_component": 0.0,
        "entity_component": 0.0,
        "pattern_component": 0.0,
        "creator_component": 0.0,
        "synthetic_penalty": 0.0,
        "rug_penalty": 0.0,
        "liquidity_component": 0.0,
        "fee_component": 0.0,
        "runner_adjustment": 0.0,
        "data_quality_component": 0.0,
        "historical_similarity_component": 0.0,
        "early_book_component": 0.0,
    }

    def plus(d: float, reason: str, component: str) -> None:
        nonlocal score, conf
        score += d
        components[component] = round(components.get(component, 0.0) + d, 2)
        pos.append({"delta": d, "reason": reason, "component": component})

    def minus(d: float, reason: str, component: str) -> None:
        nonlocal score, conf
        score += d
        components[component] = round(components.get(component, 0.0) + d, 2)
        neg.append({"delta": d, "reason": reason, "component": component})

    vol = activity.volume_m5_usd
    if vol is None:
        missing.append("volume")
    else:
        # Gate 1 already used volume. Recording 0 keeps the component labeled
        # so nobody can mistake a missing key for "volume was ignored by accident."
        components["volume_component"] = 0.0

    if wallets.status == "UNKNOWN":
        missing.append("wallets")
        conf -= 0.04
    elif wallets.status == "OBSERVED":
        missing.append("wallet_history")
        conf -= 0.02
    else:
        sw = wallets.smart_wallet_count or 0
        if sw >= 3:
            plus(14, "strong early-wallet quality (sample ≥ 3)", "wallet_component")
            conf += 0.12
        elif sw >= 1:
            plus(6, "some measured-edge wallets (sample ≥ 3)", "wallet_component")
            conf += 0.06

    if creator.status == "UNKNOWN":
        missing.append("creator")
    elif (creator.historical_runners or 0) >= 3 and (creator.launches or 0) >= 5:
        plus(12, "proven creator (stored runners, sample ≥ 5 launches)", "creator_component")
        conf += 0.08
    elif creator.serial_risk == "HIGH":
        minus(-8, "serial deployer", "creator_component")
    elif creator.status == "OBSERVED":
        missing.append("creator_sample")

    intel_matches = [
        m for m in patterns.matches
        if m.get("kind") in ("measured_edge", "historical_resemblance", "repeat_early_buyer")
    ]
    if intel_matches:
        plus(8, "historical/edge pattern match", "pattern_component")
        conf += 0.05
    elif patterns.pattern_confidence == "UNKNOWN":
        missing.append("patterns")
    if any(m.get("kind") == "historical_failure_resemblance" for m in patterns.matches):
        minus(-6, "resembles stored fade fingerprints (sample ≥ 5, not a probability)", "pattern_component")

    if synthetic.level == "UNKNOWN":
        missing.append("synthetic")
    elif synthetic.level == "CRITICAL":
        minus(-16, "critical synthetic activity", "synthetic_penalty")
    elif synthetic.level == "HIGH":
        minus(-8, "elevated synthetic activity", "synthetic_penalty")
    elif synthetic.level == "MEDIUM":
        minus(-4, "moderate synthetic activity", "synthetic_penalty")

    if rug.level in ("HIGH", "CRITICAL"):
        minus(-10 if rug.level == "HIGH" else -18, f"rug risk {rug.level}", "rug_penalty")
    elif rug.level == "UNKNOWN":
        missing.append("rug")

    liq = activity.liquidity_usd
    if liq is None:
        missing.append("liquidity")
    elif liq < 5_000:
        minus(-6, "thin liquidity", "liquidity_component")
    elif liq >= 40_000:
        plus(4, "solid liquidity", "liquidity_component")

    if entity_link_count >= 1:
        plus(4, f"{entity_link_count} prior co-buy relationship(s) as-of", "entity_component")
        conf += 0.03

    if fee_status == "VERIFIED" and global_fees_sol is not None:
        if global_fees_sol + 1e-9 >= 1.0:
            plus(4, "verified global fees ≥ 1 SOL (optional evidence)", "fee_component")
        else:
            minus(-3, "verified global fees < 1 SOL (optional evidence)", "fee_component")

    if runner.score is not None and runner.score >= 70:
        plus(4, "runner potential elevated (score, not a probability)", "runner_adjustment")
    elif runner.score is not None and runner.score <= 35:
        minus(-4, "runner potential weak (score, not a probability)", "runner_adjustment")

    score = max(0.0, min(100.0, score))
    conf = max(0.1, min(0.95, conf - 0.04 * len(missing)))
    components["final_score"] = round(score, 1)
    components["confidence_adjustment"] = round(conf, 2)
    components["data_quality_component"] = 0.0  # missingness lives in missing_data, not a hidden boost
    return ScoreBreakdown(
        score=round(score, 1),
        confidence=round(conf, 2),
        positive=pos,
        negative=neg,
        missing=missing,
        components=components,
        promotable=False,
        actionable=False,
        interpretation="INSUFFICIENT_EVIDENCE",
    )


def _layer_quality(status: str, missing: list[str], confidence: float | None) -> dict[str, Any]:
    if status == "UNKNOWN":
        grade = "UNKNOWN"
    elif status == "OBSERVED":
        grade = "LOW"
    elif missing:
        grade = "MEDIUM"
    else:
        grade = "HIGH"
    return {
        "status": status,
        "confidence": grade if confidence is None else ("HIGH" if confidence >= 0.7 else "MEDIUM" if confidence >= 0.4 else "LOW"),
        "completeness": 0.0 if status == "UNKNOWN" else (0.4 if status == "OBSERVED" else 0.8),
        "missing_fields": list(missing),
    }


def build_data_quality(
    *,
    wallets: WalletIntel,
    creator: CreatorProfile,
    synthetic: RiskResult,
    rug: RiskResult,
    patterns: PatternResult,
    entities: Mapping[str, Any],
    activity: MarketActivity,
    fee_status: str,
) -> dict[str, Any]:
    layers = {
        "market": _layer_quality(
            "OBSERVED" if activity.volume_m5_usd is not None else "UNKNOWN",
            [] if activity.volume_m5_usd is not None else ["volume_m5"],
            0.9 if activity.volume_m5_usd is not None else None,
        ),
        "wallets": _layer_quality(wallets.status, wallets.missing, None),
        "creator": _layer_quality(creator.status, creator.missing, creator.confidence),
        "synthetic": _layer_quality(synthetic.level if synthetic.level != "UNKNOWN" else "UNKNOWN", synthetic.missing, synthetic.confidence),
        "rug": _layer_quality(rug.level if rug.level != "UNKNOWN" else "UNKNOWN", rug.missing, rug.confidence),
        "patterns": _layer_quality(
            "UNKNOWN" if patterns.pattern_confidence == "UNKNOWN" else "OBSERVED",
            patterns.missing,
            patterns.confidence_value,
        ),
        "entities": _layer_quality(str(entities.get("status") or "UNKNOWN"), list(entities.get("missing") or []), None),
        "fees": _layer_quality("KNOWN" if fee_status == "VERIFIED" else "UNKNOWN", [] if fee_status == "VERIFIED" else ["global_fees_sol"], None),
    }
    critical = [layers["wallets"]["confidence"], layers["creator"]["confidence"], layers["synthetic"]["confidence"]]
    order = {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
    weakest = min(critical, key=lambda g: order.get(g, 0))
    observed = sum(1 for v in layers.values() if v["status"] not in ("UNKNOWN",))
    completeness = round(observed / max(1, len(layers)), 2)
    return {
        "overall": weakest,
        "weakest_critical": "wallets" if layers["wallets"]["confidence"] == weakest else (
            "creator" if layers["creator"]["confidence"] == weakest else "synthetic"
        ),
        "data_completeness": completeness,
        "source_coverage": {k: v["status"] for k, v in layers.items()},
        "layers": layers,
        "freshness": "as_of_decision",
        "note": "Overall respects the weakest critical evidence. UNKNOWN is not bullish.",
    }


def why_this_ca(inv: Investigation) -> dict[str, Any]:
    """Human-readable evidence. Missing stays UNKNOWN. Not a probability."""
    cares: list[str] = []
    unknown: list[str] = []
    vol = inv.activity.volume_m5_usd
    if vol is not None:
        cares.append(f"${vol:,.0f} 5m volume triggered investigation. Volume is not a buy.")
    buyers = inv.wallets.meaningful_buyer_count
    if buyers:
        cares.append(f"{buyers} meaningful early buyers identified.")
    else:
        unknown.append("Meaningful early buyers: UNKNOWN")
    smart = inv.wallets.smart_wallet_count or 0
    if smart:
        cares.append(f"{smart} have measurable historical edge (sample ≥ 3).")
    else:
        unknown.append("Historical wallet edge: UNKNOWN (need ≥ 3 resolved prior outcomes)")
    if (inv.wallets.winner_count or 0) or (inv.wallets.loser_count or 0):
        cares.append(f"Winners {inv.wallets.winner_count or 0} / losers {inv.wallets.loser_count or 0} among known-edge wallets.")
    links = int((inv.entities or {}).get("link_count") or 0)
    if links:
        cares.append(f"{links} prior co-buy relationship(s) as-of.")
    else:
        unknown.append("Entity co-buy clusters: UNKNOWN")
    if inv.creator.status == "KNOWN" and inv.creator.launches:
        cares.append(
            f"Creator has {inv.creator.launches} prior launches as-of: "
            f"{inv.creator.historical_runners or 0} runners / {inv.creator.historical_fades or 0} fades."
        )
        if inv.creator.success_rate is None:
            unknown.append("Creator success rate: UNKNOWN (resolved < 3)")
    elif inv.creator.status == "OBSERVED":
        unknown.append("Creator history: OBSERVED only (tiny sample, not intelligence)")
    else:
        unknown.append("Creator: UNKNOWN")
    res = inv.patterns.resemblance or {}
    sample = res.get("sample_count") or 0
    if res.get("confidence") not in (None, "UNKNOWN") and sample >= 5:
        cares.append(
            f"Buyer/market structure resembles {sample} historical launches as-of: "
            f"{res.get('runner_matches') or 0} runners / {res.get('held_matches') or 0} held / "
            f"{res.get('fade_matches') or 0} fades (not a probability)."
        )
    else:
        unknown.append("Historical fingerprint resemblance: UNKNOWN (need ≥ 5 matches and ≥ 3 informative bands)")
    sim = inv.similarity or {}
    if sim.get("sample_count"):
        cares.append(
            f"Historical analogues as-of: {sim.get('runner_matches') or 0} RUNNER / "
            f"{sim.get('held_matches') or 0} HELD / {sim.get('fade_matches') or 0} FADE "
            f"(strong {sim.get('strong_matches') or 0} / moderate {sim.get('moderate_matches') or 0} / "
            f"weak {sim.get('weak_matches') or 0}; not a probability)."
        )
    cares.append(f"Synthetic indicators: {inv.synthetic.level}")
    cares.append(f"Rug indicators: {inv.rug.level}")
    dq = (inv.data_quality or {}).get("overall") or "UNKNOWN"
    cares.append(f"Evidence quality: {dq}")
    if inv.fee_status != "VERIFIED":
        unknown.append("Global fees: UNKNOWN (optional evidence, not a reject)")
    unknown.append("Funding relationships: UNKNOWN")
    if inv.promote:
        expl = "Promoted: stored intelligence is sufficient. This is not a buy."
    else:
        expl = "Not promoted: we don't know → insufficient evidence → don't promote."
    return {
        "headline": "WHY STINKY CARES" if inv.has_intelligence else "INSUFFICIENT EVIDENCE",
        "cares": cares,
        "unknown": unknown,
        "promote": inv.promote,
        "promote_explanation": expl,
        "calibrated_probability": False,
    }


def information_advantage(inv: Investigation) -> dict[str, Any]:
    """How much Stinky added beyond a volume-only scanner. Not financial alpha."""
    facts: list[str] = []
    stinky: dict[str, Any] = {
        "meaningful_buyers": inv.wallets.meaningful_buyer_count,
        "edge_wallets": inv.wallets.smart_wallet_count,
        "winners": inv.wallets.winner_count,
        "losers": inv.wallets.loser_count,
        "creator_launches": inv.creator.launches,
        "creator_runners": inv.creator.historical_runners,
        "creator_fades": inv.creator.historical_fades,
        "entity_clusters": (inv.entities or {}).get("link_count"),
        "historical_matches": (inv.patterns.resemblance or {}).get("sample_count"),
        "historical_runners": (inv.patterns.resemblance or {}).get("runner_matches"),
        "synthetic": inv.synthetic.level,
        "rug": inv.rug.level,
        "data_quality": (inv.data_quality or {}).get("overall"),
    }
    if inv.wallets.meaningful_buyer_count:
        facts.append(f"{inv.wallets.meaningful_buyer_count} meaningful early buyers")
    if inv.wallets.smart_wallet_count:
        facts.append(f"{inv.wallets.smart_wallet_count} historical-edge wallets")
    if inv.creator.launches:
        facts.append(f"creator: {inv.creator.launches} prior launches as-of")
    links = int((inv.entities or {}).get("link_count") or 0)
    if links:
        facts.append(f"{links} recurring wallet cluster(s)")
    sample = int((inv.patterns.resemblance or {}).get("sample_count") or 0)
    if sample >= 5 and (inv.patterns.resemblance or {}).get("confidence") not in (None, "UNKNOWN"):
        facts.append(f"{sample} historical fingerprint matches")
        facts.append(f"{(inv.patterns.resemblance or {}).get('runner_matches') or 0} historical runners")
    if inv.synthetic.level not in ("UNKNOWN",):
        facts.append(f"synthetic {inv.synthetic.level}")
    if inv.rug.level not in ("UNKNOWN",):
        facts.append(f"rug {inv.rug.level}")
    n = len(facts)
    status = "NONE" if n == 0 else ("PARTIAL" if n < 3 else "MATERIAL")
    return {
        "volume_scanner": {
            "volume_m5_usd": inv.activity.volume_m5_usd,
            "claim": "volume print only",
        },
        "stinky": stinky,
        "advantage_facts": facts,
        "advantage_count": n,
        "advantage_status": status,
        "note": "Not financial alpha. Count of evidence layers beyond the volume print.",
        "calibrated_probability": False,
    }


def _has_intelligence(wallets: WalletIntel, creator: CreatorProfile, activity: MarketActivity) -> bool:
    """Volume is not intelligence. Tiny creator samples are not intelligence."""
    if wallets.status == "KNOWN" and (wallets.smart_wallet_count or 0) >= 1:
        return True
    if creator.status == "KNOWN" and (creator.launches or 0) >= 3:
        return True
    return False


def pipeline_status(
    *,
    gate1_passed: bool,
    investigation: Investigation | None,
) -> str:
    if not gate1_passed:
        return STATUS_REJECTED
    if investigation is None:
        return STATUS_DISCOVERED
    if not investigation.complete:
        return STATUS_INVESTIGATING
    if investigation.synthetic.level == "CRITICAL" or investigation.rug.level == "CRITICAL":
        return STATUS_HIGH_RISK
    if investigation.synthetic.level == "HIGH" or investigation.rug.level == "HIGH":
        return STATUS_HIGH_RISK
    if not investigation.has_intelligence:
        return STATUS_UNKNOWN
    return STATUS_QUALIFIED


def _would_change(wallets: WalletIntel, creator: CreatorProfile, patterns: PatternResult, synthetic: RiskResult, rug: RiskResult) -> list[str]:
    out: list[str] = []
    if wallets.status != "KNOWN":
        out.append("stored early-wallet track records with sample ≥ 3 (would enable wallet intelligence)")
    if creator.status != "KNOWN":
        out.append("creator launch history with ≥ 3 prior mints as-of (would enable creator intelligence)")
    if patterns.pattern_confidence == "UNKNOWN" or "historical_similarity" in patterns.missing or "historical_similarity_sample" in patterns.missing:
        out.append("≥5 as-of fingerprint matches (would allow historical resemblance)")
    if synthetic.level == "UNKNOWN":
        out.append("flow coverage (concentration + diversity + size/timing) so synthetic can be LOW or a confirmed risk")
    if rug.level == "UNKNOWN":
        out.append("liquidity + creator history so rug is not UNKNOWN")
    return out


def _build_evidence(
    *,
    activity: MarketActivity,
    synthetic: RiskResult,
    rug: RiskResult,
    wallets: WalletIntel,
    creator: CreatorProfile,
    patterns: PatternResult,
    entities: Mapping[str, Any],
    fee_status: str,
    promote: bool,
    insufficient: bool,
    would_change: list[str],
) -> EvidenceBundle:
    b = EvidenceBundle(promote=promote, insufficient_evidence=insufficient, would_change_conclusion=list(would_change))
    vol_st = "OBSERVED" if activity.volume_m5_usd is not None else "MISSING"
    b.add(eitem("MARKET", "volume_5m", activity.volume_m5_usd, status=vol_st, source="market", explanation="5-minute volume is Gate 1 (investigation trigger). It is not a bullish score."))
    b.add(eitem("MARKET", "liquidity", activity.liquidity_usd, status="OBSERVED" if activity.liquidity_usd is not None else "MISSING", source="market", explanation="Liquidity USD"))
    b.add(eitem("MARKET", "volume_liquidity_ratio", activity.volume_liquidity_ratio, status="OBSERVED" if activity.volume_liquidity_ratio is not None else "MISSING", source="derived", explanation="Volume / liquidity"))
    b.add(eitem("FLOW", "unique_wallets", activity.unique_wallets, status="OBSERVED" if activity.unique_wallets is not None else "MISSING", source="book", explanation="Unique wallets on observed book"))
    b.add(eitem("FLOW", "wallet_concentration", activity.top4_wallet_volume_share, status="OBSERVED" if activity.top4_wallet_volume_share is not None else "MISSING", source="book", explanation="Top-4 volume share"))
    b.add(eitem("FLOW", "synthetic_level", synthetic.level, status="UNKNOWN" if synthetic.level == "UNKNOWN" else "OBSERVED", source=synthetic.model_version, explanation="Synthetic conclusion; HIGH needs ≥2 families", confidence=synthetic.confidence))
    b.add(eitem("CREATOR", "status", creator.status, status=creator.status if creator.status != "KNOWN" else "KNOWN", source="creator_store", explanation="Creator history as-of", confidence=creator.confidence))
    b.add(eitem("WALLETS", "status", wallets.status, status=wallets.status if wallets.status != "KNOWN" else "KNOWN", source="wallet_memory", explanation="Early-wallet intelligence as-of"))
    b.add(eitem("WALLETS", "smart_wallet_count", wallets.smart_wallet_count, status="KNOWN" if wallets.smart_wallet_count else "UNKNOWN", source="wallet_memory", explanation="Wallets with sample ≥ 3"))
    b.add(eitem("WALLETS", "winners", wallets.winner_count, status="OBSERVED" if wallets.winner_count is not None else "MISSING", source="wallet_memory", explanation="Prior-edge wallets with hit_rate ≥ 0.5"))
    b.add(eitem("WALLETS", "losers", wallets.loser_count, status="OBSERVED" if wallets.loser_count is not None else "MISSING", source="wallet_memory", explanation="Prior-edge wallets with hit_rate < 0.5"))
    b.add(eitem("ENTITY", "link_count", entities.get("link_count"), status=str(entities.get("status") or "UNKNOWN"), source="relationship_memory", explanation="Prior co-buy links as-of"))
    b.add(eitem("PATTERN", "confidence", patterns.pattern_confidence, status="UNKNOWN" if patterns.pattern_confidence == "UNKNOWN" else "OBSERVED", source="pattern_memory", explanation="Structural/as-of pattern match"))
    b.add(eitem("DATA_QUALITY", "fee_status", fee_status, status="UNKNOWN" if fee_status != "VERIFIED" else "KNOWN", source="fee_resolver", explanation="Global fees are optional evidence, never admission"))
    b.add(eitem("DATA_QUALITY", "promote", promote, status="OBSERVED", source="intel", explanation="UNKNOWN/insufficient never promotes"))
    return b


def investigation_report(inv: Investigation) -> dict[str, Any]:
    """Machine + human investigation card. Missing stays UNKNOWN. Not a buy."""
    sim = inv.similarity or {}
    wr = inv.wallets.reputation or {}
    cr = inv.creator.reputation or {}
    score_display: Any
    if inv.insufficient_evidence or not inv.score.actionable or inv.score.interpretation == "INSUFFICIENT_EVIDENCE":
        score_display = "UNK"
    else:
        score_display = inv.score.score
    return {
        "headline": "STINKY INVESTIGATION",
        "ca": inv.mint,
        "protocol": None,
        "gate1_volume": inv.activity.volume_m5_usd,
        "status": inv.pipeline_status,
        "promote": inv.promote,
        "creator": {
            "status": inv.creator.status,
            "reputation": cr.get("tier") or "UNKNOWN",
            "launches": inv.creator.launches,
            "runners": inv.creator.historical_runners,
            "fades": inv.creator.historical_fades,
            "confidence": cr.get("confidence") if cr else inv.creator.confidence,
            "sample_size": cr.get("sample_size"),
            "risk": inv.creator.serial_risk or "UNKNOWN",
        },
        "early_buyers": {
            "meaningful": inv.wallets.meaningful_buyer_count,
            "measured": inv.wallets.smart_wallet_count,
            "unknown": inv.wallets.unknown_wallet_count,
            "concentration": inv.activity.top4_wallet_volume_share,
            "reputation": wr.get("tier") or "UNKNOWN",
        },
        "smart_money": {
            "measured_wallets": inv.wallets.smart_wallet_count,
            "historical_edge": inv.wallets.avg_hit_rate,
            "confidence": wr.get("confidence"),
            "sample_resolved": wr.get("sample_resolved"),
        },
        "patterns": {
            "detected": [m.get("kind") for m in inv.patterns.matches],
            "confidence": inv.patterns.pattern_confidence,
        },
        "historical_matches": {
            "strong": sim.get("strong_matches"),
            "moderate": sim.get("moderate_matches"),
            "weak": sim.get("weak_matches"),
            "runner": sim.get("runner_matches"),
            "held": sim.get("held_matches"),
            "fade": sim.get("fade_matches"),
            "unknown": sim.get("unknown_matches"),
            "runner_similarity": sim.get("runner_similarity") or "UNKNOWN",
            "similarity_score": sim.get("similarity_score"),
            "similarity_confidence": sim.get("similarity_confidence") or "UNKNOWN",
            "calibrated_probability": False,
        },
        "risk": {
            "synthetic": inv.synthetic.level,
            "rug": inv.rug.level,
            "concentration": inv.activity.top4_wallet_volume_share,
        },
        "verdict": {
            "pipeline_status": inv.pipeline_status,
            "has_intelligence": inv.has_intelligence,
            "promote": inv.promote,
            "score": score_display,
            "interpretation": inv.score.interpretation,
            "note": (
                "Promoted: stored intelligence is sufficient. This is not a buy."
                if inv.promote
                else "We don't know → insufficient evidence → don't promote."
            ),
        },
        "calibrated_probability": False,
    }


def investigate(
    bundle: Mapping[str, Any],
    *,
    memory: IntelligenceMemory | None = None,
) -> Investigation:
    """Run the full desk. Missing stays UNKNOWN. Memory queries are as-of."""
    t0 = perf_counter()
    mint = str(bundle.get("mint") or "").strip() or None
    creator_addr = str(bundle["creator"]).strip() if bundle.get("creator") else None
    as_of = bundle.get("decision_timestamp") or bundle.get("as_of")
    trades = bundle.get("trades")
    if isinstance(trades, list) and trades:
        activity = activity_from_trades(
            mint=mint,
            trades=trades,
            volume_m5_usd=_f(bundle.get("volume_m5_usd") if bundle.get("volume_m5_usd") is not None else bundle.get("volume_usd")),
            liquidity_usd=_f(bundle.get("liquidity_usd")),
            market_cap_usd=_f(bundle.get("market_cap_usd")),
            txns_m5_buys=_i(bundle.get("txns_m5_buys")),
            txns_m5_sells=_i(bundle.get("txns_m5_sells")),
            creator=creator_addr,
        )
    else:
        activity = market_activity_from_mapping(bundle)

    synthetic = assess_synthetic(activity)
    buyers = bundle.get("buyers") if isinstance(bundle.get("buyers"), list) else None
    perf = bundle.get("wallet_performance") if isinstance(bundle.get("wallet_performance"), Mapping) else None
    creator_raw = bundle.get("creator_profile") if isinstance(bundle.get("creator_profile"), Mapping) else None
    hist = bundle.get("historical_patterns") if isinstance(bundle.get("historical_patterns"), Mapping) else None
    entities: dict[str, Any] = {"status": "UNKNOWN", "links": [], "link_count": 0, "missing": ["prior_co_buy"]}

    if memory is not None:
        wallet_ids = []
        for b in buyers or []:
            w = str(b.get("wallet") or b.get("userAddress") or "").strip()
            if w:
                wallet_ids.append(w)
        # Memory as-of is the source of truth. Bundle wallet_performance is ignored
        # unless explicitly marked as-of, in which case it may fill gaps.
        mem_perf = memory.wallet_performance_as_of(wallet_ids, as_of=as_of, exclude_mint=mint) if wallet_ids else {}
        if bundle.get("wallets_as_of_decision") and perf:
            merged = dict(mem_perf)
            for k, v in perf.items():
                merged.setdefault(k, v)
            perf = merged
        else:
            perf = mem_perf or None
        mem_creator = memory.creator_profile_as_of(creator_addr, as_of=as_of, exclude_mint=mint) if creator_addr else None
        if mem_creator:
            creator_raw = mem_creator
        if wallet_ids:
            entities = memory.relationships_as_of(wallet_ids, as_of=as_of, exclude_mint=mint)

    creator = build_creator_profile(creator_raw)
    wallets = analyze_wallets(buyers, perf)
    fp = book_fingerprint(
        top4_wallet_volume_share=activity.top4_wallet_volume_share,
        unique_wallets=activity.unique_wallets if activity.unique_wallets is not None else wallets.unique_wallets,
        volume_m5_usd=activity.volume_m5_usd,
        smart_wallet_count=wallets.smart_wallet_count,
        creator_launches=creator.launches,
        repeated_size_share=activity.repeated_size_share,
        liquidity_usd=activity.liquidity_usd,
        buy_sell_imbalance=activity.buy_sell_imbalance,
        entity_link_count=int(entities.get("link_count") or 0) if entities.get("status") == "KNOWN" else None,
        synthetic_level=synthetic.level,
    )
    feats = fingerprint_features(
        top4_wallet_volume_share=activity.top4_wallet_volume_share,
        unique_wallets=activity.unique_wallets if activity.unique_wallets is not None else wallets.unique_wallets,
        volume_m5_usd=activity.volume_m5_usd,
        smart_wallet_count=wallets.smart_wallet_count,
        creator_launches=creator.launches,
        repeated_size_share=activity.repeated_size_share,
        liquidity_usd=activity.liquidity_usd,
        market_cap_usd=activity.market_cap_usd,
        buy_sell_imbalance=activity.buy_sell_imbalance,
        entity_link_count=int(entities.get("link_count") or 0) if entities.get("status") == "KNOWN" else None,
        synthetic_level=synthetic.level,
        meaningful_buyer_count=wallets.meaningful_buyer_count,
    )
    if memory is not None and hist is None:
        hist = memory.pattern_match_as_of(fp, as_of=as_of, exclude_mint=mint)
    patterns = match_patterns(wallets=wallets, creator=creator, activity=activity, historical=hist)
    rug = assess_rug(
        activity,
        creator_launches=creator.launches,
        creator_runner_rate=(
            (creator.historical_runners / creator.launches)
            if creator.launches and creator.historical_runners is not None and creator.launches > 0
            else None
        ),
        creator_known=True if creator.status == "KNOWN" else None,
        synthetic=synthetic,
    )
    fee_status = str(bundle.get("fee_status") or "UNKNOWN")
    fees = _f(bundle.get("global_fees_sol"))
    if fee_status not in ("VERIFIED", "UNKNOWN", "UNSUPPORTED"):
        fee_status = "UNKNOWN"
        fees = None
    if fee_status != "VERIFIED":
        fees = None
    volume_gate = _f(bundle.get("volume_gate")) or 150_000.0
    runner = runner_potential(
        activity=activity,
        synthetic=synthetic,
        rug=rug,
        wallets=wallets,
        creator=creator,
        patterns=patterns,
        volume_gate=volume_gate,
    )
    score = compose_stinky_score(
        activity=activity,
        synthetic=synthetic,
        rug=rug,
        wallets=wallets,
        creator=creator,
        patterns=patterns,
        runner=runner,
        fee_status=fee_status,
        global_fees_sol=fees,
        volume_gate=volume_gate,
        entity_link_count=int(entities.get("link_count") or 0),
    )
    intel = _has_intelligence(wallets, creator, activity)
    missing = sorted(
        set(synthetic.missing + rug.missing + creator.missing + wallets.missing + patterns.missing + runner.missing + score.missing)
    )
    would = _would_change(wallets, creator, patterns, synthetic, rug)
    inv = Investigation(
        mint=mint,
        complete=True,
        pipeline_status=STATUS_INVESTIGATING,
        activity=activity,
        synthetic=synthetic,
        rug=rug,
        creator=creator,
        wallets=wallets,
        patterns=patterns,
        runner=runner,
        score=score,
        fee_status=fee_status,
        global_fees_sol=fees,
        has_intelligence=intel,
        missing_data=missing,
        promote=False,
        insufficient_evidence=not intel,
        would_change=would,
        entities=entities,
        fingerprint=fp,
        fingerprint_features=feats,
        decision_timestamp=str(as_of) if as_of is not None else None,
    )
    inv.pipeline_status = pipeline_status(gate1_passed=True, investigation=inv)
    inv.promote = inv.pipeline_status == STATUS_QUALIFIED and intel
    inv.insufficient_evidence = not intel
    inv.score.promotable = inv.promote
    if not intel:
        # UNKNOWN is not a grade. Do not leave a 50-ish number that looks mid-pack.
        inv.runner = RunnerPotential(
            score=None,
            confidence=None,
            positive=inv.runner.positive,
            negative=inv.runner.negative,
            missing=inv.runner.missing,
        )
        inv.score.actionable = False
        inv.score.interpretation = "INSUFFICIENT_EVIDENCE"
    else:
        inv.score.actionable = inv.pipeline_status in (STATUS_QUALIFIED, STATUS_ALERT, STATUS_HIGH_RISK)
        inv.score.interpretation = "EVIDENCE_BASED"
    inv.evidence = _build_evidence(
        activity=activity, synthetic=synthetic, rug=rug, wallets=wallets, creator=creator,
        patterns=patterns, entities=entities, fee_status=fee_status,
        promote=inv.promote, insufficient=inv.insufficient_evidence, would_change=would,
    ).to_dict()
    inv.data_quality = build_data_quality(
        wallets=wallets, creator=creator, synthetic=synthetic, rug=rug,
        patterns=patterns, entities=entities, activity=activity, fee_status=fee_status,
    )
    inv.similarity = historical_similarity(
        memory, fp, as_of=as_of, exclude_mint=mint, query_features=feats,
    ) if memory is not None else historical_similarity(None, fp)
    inv.why = why_this_ca(inv)
    inv.information_advantage = information_advantage(inv)
    inv.report = investigation_report(inv)
    ENGINE_METRICS.record("investigation", (perf_counter() - t0) * 1000.0)
    ENGINE_METRICS.inc("investigations")
    ENGINE_METRICS.inc(f"pipeline_{inv.pipeline_status.lower()}")
    return inv


def can_alert_investigation(
    gate1_eligible: bool,
    investigation: Investigation | None,
    *,
    min_score: float = 55.0,
    rejection_reason: str | None = None,
) -> tuple[bool, str | None]:
    """Alert requires Gate 1 + completed inspection + acceptable risk + intelligence + score."""
    if not gate1_eligible:
        return False, rejection_reason or "NOT_ELIGIBLE"
    if investigation is None or not investigation.complete:
        return False, "INSPECTION_INCOMPLETE"
    if investigation.synthetic.level == "CRITICAL" or investigation.rug.level == "CRITICAL":
        return False, "RISK_CRITICAL"
    # Intelligence before score: a 50-point volume print is not a near-miss.
    if not investigation.has_intelligence or investigation.insufficient_evidence:
        return False, "INTELLIGENCE_INSUFFICIENT"
    if investigation.pipeline_status == STATUS_UNKNOWN:
        return False, "INTELLIGENCE_INSUFFICIENT"
    if investigation.score.score + 1e-9 < float(min_score):
        return False, "SCORE_BELOW_MIN"
    if not investigation.score.actionable:
        return False, "INTELLIGENCE_INSUFFICIENT"
    return True, None


def inspection_persist_params(
    inv: Investigation,
    *,
    alert_ok: bool,
    alert_reason: str | None,
) -> dict[str, Any]:
    import json

    return {
        "mint": inv.mint,
        "model_version": inv.model_version,
        "pipeline_status": inv.pipeline_status,
        "gate1_passed": True,
        "volume_m5_usd": inv.activity.volume_m5_usd,
        "synthetic_score": inv.synthetic.score,
        "synthetic_level": inv.synthetic.level,
        "rug_score": inv.rug.score,
        "rug_level": inv.rug.level,
        "stinky_score": inv.score.score,
        "runner_potential": inv.runner.score,
        "score_confidence": inv.score.confidence,
        "fee_status": inv.fee_status,
        "global_fees_sol": inv.global_fees_sol,
        "has_intelligence": inv.has_intelligence,
        "evidence": json.dumps(inv.to_dict()),
        "missing_data": json.dumps(list(inv.missing_data)),
        "alert_ok": bool(alert_ok),
        "alert_reason": alert_reason,
    }
