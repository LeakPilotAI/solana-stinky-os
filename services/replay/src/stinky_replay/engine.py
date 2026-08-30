"""Deterministic replay against the event store + market snapshots."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from stinky_replay.config import settings


def _canonical_gate(row: dict[str, Any]) -> tuple[bool, str | None]:
    """Same filter as live. Fail closed if core is unavailable."""
    try:
        import sys
        from pathlib import Path

        core = Path(__file__).resolve().parents[4] / "packages" / "stinky-core" / "src"
        if str(core) not in sys.path:
            sys.path.insert(0, str(core))
        from stinky_core.admission import evaluate_gate1
        from stinky_core.backtest import decision_time_snapshot
        from stinky_core.intelligence import can_alert_investigation, investigate
    except Exception:
        return False, "FILTER_UNAVAILABLE"
    snap = decision_time_snapshot(row)
    decision = evaluate_gate1(
        {
            "mint": snap.get("mint"),
            "protocol": snap.get("protocol") or snap.get("dex_id") or "pumpfun",
            "global_fees_sol": snap.get("global_fees_sol") or snap.get("fees_sol"),
            "global_fees_verified": snap.get("global_fees_verified"),
            "liquidity_usd": snap.get("liquidity_usd"),
            "volume_usd": snap.get("volume_m5_usd") or snap.get("volume_usd"),
            "market_cap_usd": snap.get("market_cap_usd"),
            "twitter": snap.get("twitter"),
            "website": snap.get("website"),
            "telegram": snap.get("telegram"),
            "migrated": True,
            "tab": "migrated",
        }
    )
    if not decision.eligible:
        return False, decision.rejection_reason
    inv = investigate(snap)
    return can_alert_investigation(True, inv, min_score=float(settings.alert_min_score))



def _engine():
    return create_async_engine(settings.database_url, pool_pre_ping=True)


class ReplayEngine:
    def __init__(self) -> None:
        self._eng = _engine()
        self._sessions = async_sessionmaker(self._eng, class_=AsyncSession, expire_on_commit=False)

    async def close(self) -> None:
        await self._eng.dispose()

    async def event_counts(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        event_type: str | None = None,
    ) -> dict[str, Any]:
        clauses = ["1=1"]
        params: dict[str, Any] = {}
        if since:
            clauses.append("occurred_at >= :since")
            params["since"] = since
        if until:
            clauses.append("occurred_at <= :until")
            params["until"] = until
        if event_type:
            clauses.append("event_type = :et")
            params["et"] = event_type
        where = " AND ".join(clauses)
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        f"""
                        SELECT event_type, COUNT(*)::int AS n
                        FROM events
                        WHERE {where}
                        GROUP BY event_type
                        ORDER BY n DESC
                        """
                    ),
                    params,
                )
            ).mappings().all()
            total = sum(int(r["n"]) for r in rows)
            return {
                "total": total,
                "by_type": {r["event_type"]: int(r["n"]) for r in rows},
                "since": since.isoformat() if since else None,
                "until": until.isoformat() if until else None,
            }

    async def score_gate_backtest(
        self,
        *,
        min_score: float | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Replay historical alert.candidate events through the score gate.

        Measured: count how many scored events would pass min_score, and of those
        how many mints later show runner-like volume in market_snapshots.
        """
        min_score = float(min_score if min_score is not None else settings.alert_min_score)
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT event_id::text,
                               occurred_at,
                               payload->>'mint' AS mint,
                               (payload->>'stinky_score')::float AS score,
                               (payload->>'confidence')::float AS confidence,
                               (payload->>'volume_m5_usd')::float AS volume_m5_usd,
                               payload->>'name' AS name,
                               payload->>'symbol' AS symbol,
                               COALESCE(payload->>'deployer', payload->>'creator') AS deployer
                        FROM events
                        WHERE event_type = 'alert.candidate'
                          AND payload->>'stinky_score' IS NOT NULL
                        ORDER BY occurred_at DESC
                        LIMIT :lim
                        """
                    ),
                    {"lim": limit},
                )
            ).mappings().all()

            evaluated = []
            seen_mints: set[str] = set()
            passed = 0
            runners = 0
            fades = 0
            unknown = 0

            for r in rows:
                score = r.get("score")
                mint = r.get("mint")
                if score is None or not mint:
                    continue
                if mint in seen_mints:
                    continue
                seen_mints.add(mint)
                payload = {
                    "mint": mint,
                    "protocol": "pumpfun",
                    "global_fees_sol": r.get("global_fees_sol") or r.get("fees_sol"),
                    "global_fees_verified": r.get("global_fees_verified"),
                    "liquidity_usd": r.get("liquidity_usd"),
                    "volume_m5_usd": r.get("volume_m5_usd"),
                    "market_cap_usd": r.get("market_cap_usd"),
                    "twitter": r.get("twitter"),
                    "stinky_score": score,
                    "score": score,
                    "meaningful_buyer_count": r.get("meaningful_buyer_count"),
                    "migrated": True,
                }
                gate_pass, _reason = _canonical_gate(payload)
                if gate_pass:
                    passed += 1

                peak = None
                snap_n = 0
                try:
                    peak_row = (
                        await session.execute(
                            text(
                                """
                                SELECT MAX(volume_m5_usd) AS peak,
                                       COUNT(*)::int AS n
                                FROM market_snapshots
                                WHERE mint = :m
                                  AND captured_at >= :at
                                """
                            ),
                            {"m": mint, "at": r["occurred_at"]},
                        )
                    ).mappings().first()
                    if peak_row:
                        peak = peak_row.get("peak")
                        snap_n = int(peak_row.get("n") or 0)
                except Exception:
                    pass

                label = "unknown"
                vol0 = r.get("volume_m5_usd")
                if snap_n == 0 or peak is None:
                    label = "unknown"
                    unknown += 1 if gate_pass else 0
                else:
                    multiple = None
                    try:
                        if vol0 and float(vol0) > 0:
                            multiple = float(peak) / float(vol0)
                    except Exception:
                        multiple = None
                    is_runner = False
                    if multiple is not None and multiple >= settings.runner_volume_multiple:
                        is_runner = True
                    if peak is not None and float(peak) >= settings.runner_peak_usd:
                        is_runner = True
                    if is_runner:
                        label = "runner"
                        if gate_pass:
                            runners += 1
                    else:
                        label = "fade"
                        if gate_pass:
                            fades += 1

                evaluated.append(
                    {
                        "mint": mint,
                        "score": score,
                        "gate_pass": gate_pass,
                        "label": label,
                        "peak_volume_m5_usd": peak,
                        "alert_volume_m5_usd": vol0,
                        "occurred_at": r["occurred_at"].isoformat()
                        if hasattr(r["occurred_at"], "isoformat")
                        else r["occurred_at"],
                        "name": r.get("name"),
                        "symbol": r.get("symbol"),
                    }
                )

            precision = (runners / passed) if passed else None
            return {
                "engine": "replay-v0.1.0-score-gate",
                "min_score": min_score,
                "candidates": len(evaluated),
                "gate_passed": passed,
                "runners_among_passed": runners,
                "fades_among_passed": fades,
                "unknown_among_passed": unknown,
                "precision_runner": precision,
                "items": evaluated[:50],
            }

    async def migration_funnel(self, *, limit_mints: int = 200) -> dict[str, Any]:
        """Replay funnel: migrated → tracked → buyers → alert.candidate."""
        async with self._sessions() as session:
            mig = (
                await session.execute(
                    text(
                        """
                        SELECT COUNT(DISTINCT payload->>'mint')::int
                        FROM events WHERE event_type = 'token.migrated'
                        """
                    )
                )
            ).scalar() or 0
            tracks = (
                await session.execute(
                    text("SELECT COUNT(*)::int FROM migration_tracks")
                )
            ).scalar() or 0
            with_buyers = (
                await session.execute(
                    text(
                        """
                        SELECT COUNT(DISTINCT mint)::int FROM migration_buyers
                        """
                    )
                )
            ).scalar() or 0
            alerts = (
                await session.execute(
                    text(
                        """
                        SELECT COUNT(DISTINCT payload->>'mint')::int
                        FROM events WHERE event_type = 'alert.candidate'
                        """
                    )
                )
            ).scalar() or 0
            return {
                "engine": "replay-v0.1.0-funnel",
                "migrations": int(mig),
                "tracks": int(tracks),
                "mints_with_buyers": int(with_buyers),
                "alert_candidates": int(alerts),
                "track_rate": (int(tracks) / int(mig)) if mig else None,
                "buyer_rate": (int(with_buyers) / int(tracks)) if tracks else None,
                "alert_rate": (int(alerts) / int(with_buyers)) if with_buyers else None,
            }
