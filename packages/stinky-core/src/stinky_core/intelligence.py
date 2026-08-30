"""Progressive intelligence after Gate 1. Deterministic, evidence-only.

Volume gets a CA onto the desk. This module decides whether it deserves attention.
Never fabricates historical similarity, fees, wallets, or scores.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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

INTEL_VERSION = "intel-v1.1.0-harden"
SCORE_VERSION = "score-v1.0.0-volume-first"
RUNNER_VERSION = "runner-potential-v1.0.0"

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
    status: str  # KNOWN | UNKNOWN
    launches: int | None = None
    migrated: int | None = None
    historical_runners: int | None = None
    historical_fades: int | None = None
    historical_unknown: int | None = None
    median_peak_multiple: float | None = None
    linked_wallets: int | None = None
    serial_risk: str | None = None
    entity_id: str | None = None
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_matches": self.matches,
            "pattern_confidence": self.pattern_confidence,
            "confidence_value": self.confidence_value,
            "pattern_evidence": self.evidence,
            "missing": list(self.missing),
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
            "model_version": self.model_version,
            "inspect_version": INSPECT_VERSION,
        }


def build_creator_profile(raw: Mapping[str, Any] | None) -> CreatorProfile:
    if not raw:
        return CreatorProfile(status="UNKNOWN", missing=["creator_store"])
    launches = _i(raw.get("launch_count") if raw.get("launch_count") is not None else raw.get("launches"))
    if launches is None and raw.get("entity_id") is None and not raw.get("known"):
        return CreatorProfile(status="UNKNOWN", missing=["creator_store"])
    runners = _i(raw.get("historical_runners") if raw.get("historical_runners") is not None else raw.get("runners"))
    fades = _i(raw.get("historical_fades") if raw.get("historical_fades") is not None else raw.get("fades"))
    serial = None
    if launches is not None:
        serial = "HIGH" if launches >= 40 else "MEDIUM" if launches >= 15 else "LOW"
    missing = []
    if runners is None:
        missing.append("historical_runners")
    return CreatorProfile(
        status="KNOWN",
        launches=launches,
        migrated=_i(raw.get("migrated") if raw.get("migrated") is not None else raw.get("migration_count")),
        historical_runners=runners,
        historical_fades=fades,
        historical_unknown=_i(raw.get("historical_unknown")),
        median_peak_multiple=_f(raw.get("median_peak_multiple")),
        linked_wallets=_i(raw.get("wallet_count") if raw.get("wallet_count") is not None else raw.get("linked_wallets")),
        serial_risk=serial,
        entity_id=str(raw["entity_id"]) if raw.get("entity_id") else None,
        missing=missing,
    )


def analyze_wallets(
    buyers: list[Mapping[str, Any]] | None,
    performance: Mapping[str, Mapping[str, Any]] | None = None,
) -> WalletIntel:
    if not buyers:
        return WalletIntel(status="UNKNOWN", missing=["early_buyers"])
    perf = performance or {}
    meaningful = 0
    smart = 0
    unknown = 0
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
        sample = early if early else tokens
        # Insufficient history is not smart money.
        if early >= 3 and tokens >= 3:
            smart += 1
            hr = _f(p.get("hit_rate"))
            if hr is not None:
                hit.append(hr)
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
    return WalletIntel(
        status=status,
        early_buyer_count=len(wallets),
        meaningful_buyer_count=meaningful,
        unique_wallets=len(set(wallets)),
        smart_wallet_count=smart,
        avg_hit_rate=(sum(hit) / len(hit)) if hit else None,
        avg_return_pct=(sum(ret) / len(ret)) if ret else None,
        unknown_wallet_count=unknown,
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

    hist = historical or {}
    resemble = _i(hist.get("similar_runner_count"))
    if resemble is None:
        missing.append("historical_similarity")
        hist_conf = "UNKNOWN"
        hist_val = None
    else:
        hist_conf = str(min(1.0, 0.15 + 0.04 * resemble))
        hist_val = min(1.0, 0.15 + 0.04 * resemble)
        evidence.append({"kind": "historical_resemblance", "value": resemble, "explanation": f"Resembles {resemble} stored runner-like tokens"})

    if wallets.status == "UNKNOWN" and creator.status == "UNKNOWN":
        missing.append("pattern_inputs")
        return PatternResult(matches=[], pattern_confidence="UNKNOWN", confidence_value=None, evidence=evidence, missing=missing)

    conf = min(1.0, 0.2 + 0.15 * len(matches))
    if hist_val is None and not matches:
        return PatternResult(matches=[], pattern_confidence="UNKNOWN", confidence_value=None, evidence=evidence, missing=missing)
    return PatternResult(
        matches=matches,
        pattern_confidence=str(round(conf, 2)),
        confidence_value=round(conf, 2),
        evidence=evidence,
        missing=missing,
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

    vol = activity.volume_m5_usd
    if vol is None:
        missing.append("volume_m5")
    else:
        used += 1
        ratio = vol / volume_gate if volume_gate else 1.0
        if ratio >= 2:
            score += 14
            pos.append({"delta": 14, "reason": f"5m volume {vol:,.0f} (≥2× Gate 1)"})
        elif ratio >= 1:
            score += 8
            pos.append({"delta": 8, "reason": f"5m volume {vol:,.0f} cleared Gate 1"})

    if wallets.status == "UNKNOWN":
        missing.append("wallets")
    else:
        used += 1
        mb = wallets.meaningful_buyer_count or 0
        if mb >= 8:
            score += 12
            pos.append({"delta": 12, "reason": f"{mb} meaningful early buyers"})
        elif mb >= 3:
            score += 6
            pos.append({"delta": 6, "reason": f"{mb} meaningful early buyers"})
        sw = wallets.smart_wallet_count or 0
        if sw >= 3:
            score += 10
            pos.append({"delta": 10, "reason": f"{sw} wallets with measured edge"})
        elif sw == 0 and mb >= 3:
            score -= 4
            neg.append({"delta": -4, "reason": "Meaningful capital without prior-edge wallets"})

    if creator.status == "UNKNOWN":
        missing.append("creator")
    else:
        used += 1
        if (creator.historical_runners or 0) >= 3:
            score += 8
            pos.append({"delta": 8, "reason": "Creator has stored runners"})
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
        used += 1
        kinds = {m.get("kind") for m in patterns.matches}
        if "measured_edge" in kinds or "dense_early_book" in kinds:
            score += 6
            pos.append({"delta": 6, "reason": "Structural pattern match on this book"})

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
) -> ScoreBreakdown:
    """Volume is the entry, not the score. Weights unchanged; components labeled."""
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
        ratio = vol / volume_gate if volume_gate else 1
        if ratio >= 2:
            plus(12, "high-quality volume (≥2× Gate 1)", "volume_component")
            conf += 0.08
        elif ratio >= 1:
            plus(6, "Gate 1 volume cleared", "volume_component")
            conf += 0.04

    if wallets.status == "UNKNOWN":
        missing.append("wallets")
        minus(-2, "no early-wallet intelligence", "wallet_component")
        conf -= 0.04
    else:
        mb = wallets.meaningful_buyer_count or 0
        sw = wallets.smart_wallet_count or 0
        if sw >= 3:
            plus(14, "strong early-wallet quality", "wallet_component")
            conf += 0.12
        elif sw >= 1:
            plus(6, "some measured-edge wallets", "wallet_component")
            conf += 0.06
        if mb >= 8:
            plus(8, "healthy buyer diversity", "wallet_component")
            conf += 0.06
        elif mb >= 3:
            plus(3, "adequate meaningful buyers", "wallet_component")

    if creator.status == "UNKNOWN":
        missing.append("creator")
    elif (creator.historical_runners or 0) >= 3:
        plus(12, "proven creator (stored runners)", "creator_component")
        conf += 0.08
    elif creator.serial_risk == "HIGH":
        minus(-8, "serial deployer", "creator_component")

    pos_matches = [m for m in patterns.matches if m.get("kind") != "serial_deployer"]
    if pos_matches:
        plus(8, "historical/structural pattern match", "pattern_component")
        conf += 0.05
    elif patterns.pattern_confidence == "UNKNOWN":
        missing.append("patterns")

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
    return ScoreBreakdown(
        score=round(score, 1),
        confidence=round(conf, 2),
        positive=pos,
        negative=neg,
        missing=missing,
        components=components,
    )


def _has_intelligence(wallets: WalletIntel, creator: CreatorProfile, activity: MarketActivity) -> bool:
    """Volume, unique-wallet counts, and trade counts are not intelligence."""
    if wallets.status == "KNOWN" and (wallets.smart_wallet_count or 0) >= 1:
        return True
    if creator.status == "KNOWN" and (creator.launches or 0) >= 1:
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


def investigate(bundle: Mapping[str, Any]) -> Investigation:
    """Run the full desk. Input keys are optional; missing stays UNKNOWN."""
    mint = str(bundle.get("mint") or "").strip() or None
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
            creator=str(bundle["creator"]) if bundle.get("creator") else None,
        )
    else:
        activity = market_activity_from_mapping(bundle)

    synthetic = assess_synthetic(activity)
    creator = build_creator_profile(bundle.get("creator_profile") if isinstance(bundle.get("creator_profile"), Mapping) else None)
    buyers = bundle.get("buyers") if isinstance(bundle.get("buyers"), list) else None
    perf = bundle.get("wallet_performance") if isinstance(bundle.get("wallet_performance"), Mapping) else None
    wallets = analyze_wallets(buyers, perf)
    hist = bundle.get("historical_patterns") if isinstance(bundle.get("historical_patterns"), Mapping) else None
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
    )
    intel = _has_intelligence(wallets, creator, activity)
    missing = sorted(
        set(synthetic.missing + rug.missing + creator.missing + wallets.missing + patterns.missing + runner.missing + score.missing)
    )
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
    )
    inv.pipeline_status = pipeline_status(gate1_passed=True, investigation=inv)
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
    if investigation.score.score + 1e-9 < float(min_score):
        return False, "SCORE_BELOW_MIN"
    if not investigation.has_intelligence:
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
