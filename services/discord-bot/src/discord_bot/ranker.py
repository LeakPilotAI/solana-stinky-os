"""Deterministic Smart Money ranking (Postgres-first, no ML).

Smart Score (0–100) is explainable and stable:
  early buys, token breadth, hit rate, returns, realized PnL.
"""

from __future__ import annotations

from typing import Any


def smart_score(row: dict[str, Any]) -> float:
    """Composite 0–100 score from wallet_performance / aggregate fields."""
    early = int(row.get("early_buy_count") or 0)
    tokens = int(row.get("tokens_purchased") or 0)
    hit = float(row.get("hit_rate") or 0.0)
    avg_ret = row.get("avg_return_pct")
    avg = float(avg_ret) if avg_ret is not None else 0.0
    pnl = float(row.get("realized_pnl_usd") or 0.0)
    wins = int(row.get("wins") or 0)
    losses = int(row.get("losses") or 0)

    score = 0.0
    score += min(40.0, early * 8.0)
    score += min(15.0, tokens * 2.0)
    score += max(0.0, min(1.0, hit)) * 25.0
    if avg > 0:
        score += min(15.0, avg / 10.0)
    if pnl > 0:
        score += min(10.0, pnl / 500.0)
    elif pnl < 0:
        score -= min(10.0, abs(pnl) / 500.0)
    sample = wins + losses
    if sample >= 5:
        score += 5.0
    elif sample >= 2:
        score += 2.0

    return round(max(0.0, min(100.0, score)), 1)


def explain_smart_score(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Human-readable deltas for Discord 'Why' style display."""
    parts: list[dict[str, Any]] = []
    early = int(row.get("early_buy_count") or 0)
    if early:
        parts.append({"delta": min(40, early * 8), "reason": f"{early} early buys"})
    tokens = int(row.get("tokens_purchased") or 0)
    if tokens:
        parts.append(
            {"delta": min(15, tokens * 2), "reason": f"{tokens} tokens purchased"}
        )
    hit = row.get("hit_rate")
    if hit is not None:
        parts.append(
            {
                "delta": round(max(0.0, min(1.0, float(hit))) * 25, 1),
                "reason": f"hit rate {float(hit) * 100:.0f}%",
            }
        )
    avg = row.get("avg_return_pct")
    if avg is not None and float(avg) > 0:
        parts.append(
            {
                "delta": round(min(15.0, float(avg) / 10.0), 1),
                "reason": f"avg return {float(avg):+.0f}%",
            }
        )
    pnl = float(row.get("realized_pnl_usd") or 0)
    if pnl != 0:
        parts.append(
            {
                "delta": round(
                    min(10.0, pnl / 500.0) if pnl > 0 else -min(10.0, abs(pnl) / 500.0),
                    1,
                ),
                "reason": f"realized PnL ${pnl:,.0f}",
            }
        )
    return parts


def rank_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach smart_score and sort descending."""
    out: list[dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        item["smart_score"] = smart_score(item)
        item["score_explanation"] = explain_smart_score(item)
        out.append(item)
    out.sort(
        key=lambda x: (
            float(x.get("smart_score") or 0),
            int(x.get("early_buy_count") or 0),
            float(x.get("hit_rate") or 0),
        ),
        reverse=True,
    )
    return out
