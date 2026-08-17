"""Deterministic Stinky Score (explainable).

AI does not invent scores (ADR-005). Pure arithmetic from known signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sentinel.models import WalletSummary


@dataclass
class ScoreResult:
    score: float
    confidence: float
    explanation: list[dict[str, float | str]] = field(default_factory=list)
    model_version: str = "score-v0.1.0-heuristic"


@dataclass
class SmartMoneySignals:
    """Aggregated early-buyer quality from wallet_performance / migration_buyers."""

    early_buyer_count: int = 0
    meaningful_buyer_count: int = 0  # early buyers with sol_spent >= threshold
    smart_wallet_count: int = 0  # early buyers with prior positive track record
    avg_hit_rate: float | None = None
    avg_return_pct: float | None = None
    top_wallets: list[dict[str, Any]] = field(default_factory=list)
    # Success learning (token_outcomes → wallet_early_success)
    success_wallet_count: int = 0  # early buyers with early_success_sample >= 2
    avg_early_success_rate: float | None = None
    mega_hunter_count: int = 0  # early_on_mega >= 1


@dataclass
class EntitySignals:
    """Operator entity context from entity-resolver (Postgres seed)."""

    entity_id: str | None = None
    launch_count: int = 0
    wallet_count: int = 1
    early_buy_count: int = 0
    confidence: float | None = None
    entity_type: str | None = None


def score_deployer(summary: WalletSummary, *, has_name: bool) -> ScoreResult:
    """v0.1 heuristic for creates — transparent and versioned.

    Base 50. Adjustments are logged in explanation.
    """
    score = 50.0
    conf = 0.25
    explanation: list[dict[str, float | str]] = []

    def add(delta: float, reason: str) -> None:
        nonlocal score
        score += delta
        explanation.append({"delta": delta, "reason": reason})

    if summary.launch_count == 0:
        add(-5, "No prior launches in our store (unknown deployer)")
        conf = 0.20
    elif summary.launch_count == 1:
        add(0, "First stored launch for this deployer")
        conf = 0.35
    elif summary.launch_count <= 5:
        add(5, f"Small history ({summary.launch_count} stored launches)")
        conf = 0.45
    elif summary.launch_count <= 20:
        add(10, f"Moderate history ({summary.launch_count} stored launches)")
        conf = 0.55
    else:
        add(-10, f"High launch volume ({summary.launch_count}) — elevated serial risk")
        conf = 0.50

    if has_name:
        add(3, "Launch metadata includes name/symbol")
    else:
        add(-2, "Missing name/symbol metadata")

    if summary.first_seen is not None:
        add(2, "Wallet age signal available")
        conf = min(1.0, conf + 0.05)

    score = max(0.0, min(100.0, score))
    conf = max(0.0, min(1.0, conf))

    return ScoreResult(
        score=round(score, 1),
        confidence=round(conf, 2),
        explanation=explanation,
        model_version="score-v0.1.0-heuristic",
    )


def score_alert_candidate(
    *,
    volume_m5_usd: float,
    threshold_usd: float,
    liquidity_usd: float | None,
    smart: SmartMoneySignals | None = None,
    entity: EntitySignals | None = None,
) -> ScoreResult:
    """v0.5 score for high-potential migration alerts.

    Base 55. Volume, liquidity, meaningful early capital, tracked smart
    wallets (hit rate + avg return from sell attribution), and entity
    serial-risk. Fully explainable (ADR-005).
    """
    score = 55.0
    conf = 0.40
    explanation: list[dict[str, float | str]] = []

    def add(delta: float, reason: str) -> None:
        nonlocal score
        score += delta
        explanation.append({"delta": delta, "reason": reason})

    # Volume overshoot vs gate
    if threshold_usd > 0 and volume_m5_usd >= threshold_usd:
        ratio = volume_m5_usd / threshold_usd
        if ratio >= 4:
            add(18, f"5m volume {volume_m5_usd:,.0f} (≥4× gate)")
            conf += 0.20
        elif ratio >= 2:
            add(12, f"5m volume {volume_m5_usd:,.0f} (≥2× gate)")
            conf += 0.15
        else:
            add(8, f"5m volume {volume_m5_usd:,.0f} (cleared ${threshold_usd:,.0f} gate)")
            conf += 0.10

    # Liquidity quality
    if liquidity_usd is not None:
        if liquidity_usd >= 100_000:
            add(8, f"Strong liquidity ${liquidity_usd:,.0f}")
            conf += 0.08
        elif liquidity_usd >= 40_000:
            add(5, f"Solid liquidity ${liquidity_usd:,.0f}")
            conf += 0.05
        elif liquidity_usd >= 15_000:
            add(2, f"Moderate liquidity ${liquidity_usd:,.0f}")
        elif liquidity_usd < 5_000:
            add(-6, f"Thin liquidity ${liquidity_usd:,.0f}")
            conf -= 0.05

    # Early-buyer + smart-money (post-migration collector + sell attribution)
    if smart is None or smart.early_buyer_count == 0:
        add(-3, "No early-buyer intelligence yet (collector may still be tracking)")
        conf = max(0.20, conf - 0.08)
    else:
        conf += min(0.12, 0.025 * smart.early_buyer_count)

        mb = smart.meaningful_buyer_count
        if mb >= 8:
            add(14, f"Strong early capital: {mb} meaningful buyers (SOL≥0.05)")
            conf += 0.12
        elif mb >= 5:
            add(10, f"Solid early capital: {mb} meaningful buyers (SOL≥0.05)")
            conf += 0.09
        elif mb >= 3:
            add(6, f"Adequate early capital: {mb} meaningful buyers (SOL≥0.05)")
            conf += 0.06
        elif mb >= 1:
            add(2, f"Thin early capital: {mb} meaningful buyer(s)")
            conf += 0.02
        elif smart.early_buyer_count >= 5:
            add(
                -2,
                f"{smart.early_buyer_count} early ranks — none with SOL≥0.05 yet",
            )
        else:
            add(-1, f"{smart.early_buyer_count} early buyers — waiting on SOL signals")

        # Prior-edge wallets (wallet_performance with sells when available)
        if smart.smart_wallet_count >= 5:
            add(
                15,
                f"{smart.smart_wallet_count} tracked smart wallets in early buyers",
            )
            conf += 0.15
        elif smart.smart_wallet_count >= 3:
            add(
                10,
                f"{smart.smart_wallet_count} tracked smart wallets in early buyers",
            )
            conf += 0.10
        elif smart.smart_wallet_count >= 1:
            add(
                5,
                f"{smart.smart_wallet_count} tracked smart wallet(s) in early buyers",
            )
            conf += 0.05
        elif mb >= 3:
            add(-1, "Meaningful capital present but no prior-edge wallets yet")

        # v0.5: hit rate / avg return now backed by sell attribution
        if smart.avg_hit_rate is not None and smart.smart_wallet_count > 0:
            if smart.avg_hit_rate >= 0.7:
                add(10, f"Smart-wallet avg hit rate {smart.avg_hit_rate*100:.0f}%")
                conf += 0.08
            elif smart.avg_hit_rate >= 0.5:
                add(6, f"Smart-wallet avg hit rate {smart.avg_hit_rate*100:.0f}%")
                conf += 0.05
            elif smart.avg_hit_rate >= 0.35:
                add(3, f"Smart-wallet avg hit rate {smart.avg_hit_rate*100:.0f}%")
            elif smart.avg_hit_rate < 0.25:
                add(-5, f"Weak smart-wallet hit rate {smart.avg_hit_rate*100:.0f}%")

        if smart.avg_return_pct is not None and smart.smart_wallet_count > 0:
            if smart.avg_return_pct >= 100:
                add(8, f"Smart-wallet avg return {smart.avg_return_pct:+.0f}%")
                conf += 0.05
            elif smart.avg_return_pct >= 40:
                add(5, f"Smart-wallet avg return {smart.avg_return_pct:+.0f}%")
            elif smart.avg_return_pct <= -30:
                add(-6, f"Smart-wallet avg return {smart.avg_return_pct:+.0f}%")
            elif smart.avg_return_pct <= -10:
                add(-3, f"Smart-wallet avg return {smart.avg_return_pct:+.0f}%")

    # v0.6 Success learning — wallets that early-bought prior runners/megas
    if smart.success_wallet_count >= 3:
        add(
            12,
            f"{smart.success_wallet_count} early buyers with measured runner history",
        )
        conf += 0.12
    elif smart.success_wallet_count >= 1:
        add(
            6,
            f"{smart.success_wallet_count} early buyer(s) with measured runner history",
        )
        conf += 0.06

    if smart.avg_early_success_rate is not None and smart.success_wallet_count > 0:
        if smart.avg_early_success_rate >= 0.5:
            add(
                10,
                f"Early-book success rate {smart.avg_early_success_rate*100:.0f}% on prior labels",
            )
            conf += 0.08
        elif smart.avg_early_success_rate >= 0.3:
            add(
                5,
                f"Early-book success rate {smart.avg_early_success_rate*100:.0f}% on prior labels",
            )
        elif smart.avg_early_success_rate < 0.15 and smart.success_wallet_count >= 2:
            add(
                -6,
                f"Weak early-book success rate {smart.avg_early_success_rate*100:.0f}%",
            )

    if smart.mega_hunter_count >= 2:
        add(8, f"{smart.mega_hunter_count} early buyers previously on mega_runner tokens")
        conf += 0.05
    elif smart.mega_hunter_count >= 1:
        add(4, "1 early buyer previously on a mega_runner token")

    # Entity / serial deployer (entity-resolver)

    if entity is None or entity.launch_count <= 0:
        add(0, "No entity profile for creator yet")
    else:
        conf += 0.05
        lc = entity.launch_count
        if lc >= 50:
            add(-14, f"Serial deployer entity: {lc} launches (high rug risk)")
            conf += 0.05
        elif lc >= 20:
            add(-10, f"Elevated serial history: {lc} launches")
            conf += 0.04
        elif lc >= 8:
            add(-5, f"Repeat deployer: {lc} launches")
        elif lc >= 2:
            add(3, f"Some launch history ({lc}) — known operator")
        else:
            add(2, "Single prior launch on entity")

        if entity.wallet_count and entity.wallet_count >= 3:
            add(
                -3,
                f"Entity links {entity.wallet_count} wallets (possible multi-wallet op)",
            )

        if entity.confidence is not None and entity.confidence >= 0.8:
            conf += 0.03

    score = max(0.0, min(100.0, score))
    conf = max(0.0, min(1.0, conf))

    return ScoreResult(
        score=round(score, 1),
        confidence=round(conf, 2),
        explanation=explanation,
        model_version="score-v0.6.0-success-learn",
    )
