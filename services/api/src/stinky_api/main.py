"""Stinky OS Intelligence API ? FastAPI entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
import structlog
from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.config import settings
from stinky_api.db import get_session
from stinky_api import queries

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("api.started", service=settings.service_name, port=settings.api_port)
    yield
    logger.info("api.stopped")


app = FastAPI(
    title="Stinky OS Intelligence API",
    version="0.1.0",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _book_memory(
    payload: dict | None,
    session: AsyncSession | None = None,
) -> tuple[Any, dict[str, int], str]:
    """Hydrate from payload snapshot, else Postgres. Empty stays empty."""
    from stinky_core.memory import IntelligenceMemory

    mem = IntelligenceMemory()
    body = payload or {}
    snap = body.get("snapshot") if isinstance(body.get("snapshot"), dict) else None
    if snap:
        return mem, mem.hydrate(snap), "payload"
    if session is not None:
        try:
            db_snap = await queries.load_memory_snapshot(session)
            return mem, mem.hydrate(db_snap), "postgres"
        except Exception:
            return mem, {}, "unavailable"
    return mem, {}, "empty"


@app.post("/v1/filter/evaluate")
async def filter_evaluate(payload: dict) -> dict:
    """Evaluate a market dict through the canonical engine. No scoring."""
    from stinky_core.admission import FILTER_VERSION, evaluate_market, filter_stats

    decision = evaluate_market(payload)
    return {
        "eligible": decision.eligible,
        "accepted": decision.accepted,
        "rejection_reason": decision.rejection_reason,
        "reason_codes": decision.reason_codes,
        "failed_filters": decision.failed_filters,
        "passed_filters": decision.passed_filters,
        "normalized_metrics": decision.normalized_metrics,
        "source_metadata": decision.source_metadata,
        "filter_version": decision.filter_version or FILTER_VERSION,
        "stats": filter_stats.snapshot(),
    }


@app.post("/v1/investigate")
async def investigate_endpoint(payload: dict) -> dict:
    """Gate 1 then investigation. Does not fabricate wallets, fees, or history."""
    from stinky_core.admission import FILTER_VERSION, evaluate_gate1
    from stinky_core.intelligence import can_alert_investigation, investigate

    decision = evaluate_gate1(payload)
    if not decision.eligible:
        return {
            "gate1_passed": False,
            "eligible": False,
            "pipeline_status": "REJECTED",
            "promote": False,
            "insufficient_evidence": True,
            "rejection_reason": decision.rejection_reason,
            "reason_codes": decision.reason_codes,
            "filter_version": decision.filter_version or FILTER_VERSION,
            "investigation": None,
            "alert_ok": False,
            "alert_reason": decision.rejection_reason,
        }
    inv = investigate(payload)
    alert_ok, alert_reason = can_alert_investigation(True, inv)
    return {
        "gate1_passed": True,
        "eligible": True,
        "pipeline_status": inv.pipeline_status,
        "promote": inv.promote,
        "insufficient_evidence": inv.insufficient_evidence,
        "has_intelligence": inv.has_intelligence,
        "stinky_score": inv.score.score,
        "score_actionable": inv.score.actionable,
        "score_interpretation": inv.score.interpretation,
        "calibrated_probability": False,
        "unknown_not_bullish": True,
        "would_change_conclusion": inv.would_change,
        "missing_data": inv.missing_data,
        "fingerprint": inv.fingerprint,
        "data_quality": inv.data_quality,
        "resemblance": inv.patterns.resemblance,
        "why": inv.why,
        "information_advantage": inv.information_advantage,
        "similarity": inv.similarity,
        "report": inv.report,
        "stages": inv.stages,
        "findings": inv.findings,
        "band_ledger": inv.band_ledger,
        "correlation_id": inv.correlation_id,
        "filter_version": decision.filter_version or FILTER_VERSION,
        "investigation": inv.to_dict(),
        "alert_ok": alert_ok,
        "alert_reason": alert_reason,
    }


@app.post("/v1/memory/as-of")
async def memory_as_of(payload: dict) -> dict:
    """As-of wallet/creator/pattern/entity query. Hydrate from snapshot. Never fabricates."""
    from stinky_core.memory import IntelligenceMemory

    mem = IntelligenceMemory()
    snap = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else None
    loaded = mem.hydrate(snap) if snap else {}
    as_of = payload.get("as_of") or payload.get("decision_timestamp")
    exclude = payload.get("exclude_mint") or payload.get("mint")
    wallets = payload.get("wallets") if isinstance(payload.get("wallets"), list) else []
    creator = payload.get("creator")
    fingerprint = payload.get("fingerprint")
    return {
        "memory_version": mem.version,
        "hydrated": loaded,
        "as_of": as_of,
        "exclude_mint": exclude,
        "wallets": mem.wallet_performance_as_of(wallets, as_of=as_of, exclude_mint=exclude) if wallets else {},
        "creator": mem.creator_profile_as_of(creator, as_of=as_of, exclude_mint=exclude) if creator else None,
        "entities": mem.relationships_as_of(wallets, as_of=as_of, exclude_mint=exclude) if wallets else {"status": "UNKNOWN", "links": [], "link_count": 0},
        "patterns": mem.pattern_match_as_of(fingerprint, as_of=as_of, exclude_mint=exclude) if fingerprint else {"confidence": "UNKNOWN", "missing": ["fingerprint"]},
        "stats": mem.to_stats(),
        "calibrated_probability": False,
    }


@app.get("/v1/memory/stats")
async def memory_stats(session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    """Live table counts. Empty/unavailable is reported, never invented."""
    from sqlalchemy import text

    tables = (
        "wallet_observations",
        "wallet_outcome_labels",
        "creator_observations",
        "creator_outcome_labels",
        "wallet_relationships",
        "pattern_fingerprints",
        "pattern_outcomes",
        "intelligence_decisions",
        "market_inspections",
        "market_observations",
        "intelligence_investigations",
        "quality_state_transitions",
    )
    counts: dict[str, Any] = {}
    available = True
    for t in tables:
        try:
            n = (await session.execute(text(f"SELECT COUNT(*) FROM {t}"))).scalar()
            counts[t] = int(n or 0)
        except Exception as exc:
            counts[t] = None
            counts[f"{t}_error"] = type(exc).__name__
            available = False
    return {"available": available, "counts": counts, "source": "postgres" if available else "unavailable"}


@app.post("/v1/book/time-machine")
async def book_time_machine(
    payload: dict, session: Annotated[AsyncSession, Depends(get_session)]
) -> dict:
    """As-of replay for one mint. Future outcomes are hidden. Never fabricates."""
    from stinky_core.book import time_machine

    mem, loaded, source = await _book_memory(payload, session)
    mint = str(payload.get("mint") or "").strip()
    if not mint:
        return {"error": "mint required", "calibrated_probability": False, "source": source, "hydrated": loaded}
    as_of = payload.get("as_of") or payload.get("decision_timestamp")
    bundle = payload.get("bundle") if isinstance(payload.get("bundle"), dict) else payload
    out = time_machine(mint=mint, as_of=as_of, bundle=bundle, memory=mem)
    out["source"] = source
    return out


@app.post("/v1/book")
async def book_summary(
    payload: dict | None = None, session: Annotated[AsyncSession, Depends(get_session)] = None
) -> dict:
    """Wallet/creator/pattern ledgers. Empty is empty, never invented."""
    from stinky_core.book import book_stats, creator_book, pattern_book, wallet_book

    mem, loaded, source = await _book_memory(payload, session)
    as_of = (payload or {}).get("as_of")
    return {
        "hydrated": loaded,
        "source": source,
        "stats": book_stats(mem, as_of=as_of),
        "wallets": wallet_book(mem, as_of=as_of),
        "creators": creator_book(mem, as_of=as_of),
        "patterns": pattern_book(mem, as_of=as_of),
        "calibrated_probability": False,
    }


@app.post("/v1/book/similarity")
async def book_similarity(
    payload: dict, session: Annotated[AsyncSession, Depends(get_session)]
) -> dict:
    """Historical analogues. Shows runners AND fades. Not a probability."""
    from stinky_core.similarity import historical_similarity

    mem, loaded, source = await _book_memory(payload, session)
    out = historical_similarity(
        mem,
        payload.get("fingerprint"),
        as_of=payload.get("as_of") or payload.get("decision_timestamp"),
        exclude_mint=payload.get("exclude_mint") or payload.get("mint"),
        query_features=payload.get("features") if isinstance(payload.get("features"), dict) else None,
    )
    out["source"] = source
    out["hydrated"] = loaded
    return out


@app.post("/v1/book/life-slices")
async def book_life_slices(
    payload: dict, session: Annotated[AsyncSession, Depends(get_session)]
) -> dict:
    """T+ market path. Future ticks after as_of are hidden."""
    from stinky_core.book import life_slices

    mem, loaded, source = await _book_memory(payload, session)
    mint = str(payload.get("mint") or "").strip()
    if not mint:
        return {"error": "mint required", "calibrated_probability": False, "source": source}
    out = life_slices(
        mem,
        mint=mint,
        t0=payload.get("t0") or payload.get("decision_timestamp") or payload.get("as_of"),
        as_of=payload.get("as_of"),
    )
    out["source"] = source
    out["hydrated"] = loaded
    return out


@app.post("/v1/book/report")
async def book_report(
    payload: dict, session: Annotated[AsyncSession, Depends(get_session)]
) -> dict:
    """Structured investigation card. Gate 1 then investigate. Never fabricates."""
    from stinky_core.admission import evaluate_gate1
    from stinky_core.intelligence import investigate

    decision = evaluate_gate1(payload)
    if not decision.eligible:
        return {
            "gate1_passed": False,
            "report": {
                "status": "REJECTED",
                "verdict": {"score": "UNK", "promote": False, "note": "Gate 1 rejected"},
            },
            "calibrated_probability": False,
        }
    mem, _loaded, source = await _book_memory(payload, session)
    inv = investigate(payload, memory=mem)
    return {
        "gate1_passed": True,
        "report": inv.report,
        "similarity": inv.similarity,
        "stages": inv.stages,
        "findings": inv.findings,
        "would_change_conclusion": inv.would_change,
        "source": source,
        "calibrated_probability": False,
    }


@app.post("/v1/book/health")
async def book_health(
    payload: dict | None = None, session: Annotated[AsyncSession, Depends(get_session)] = None
) -> dict:
    """Dataset health. Empty book is empty. Never invented."""
    from stinky_core.book import dataset_health, desk_snapshot

    mem, loaded, source = await _book_memory(payload, session)
    as_of = (payload or {}).get("as_of")
    return {
        "hydrated": loaded,
        "source": source,
        "health": dataset_health(mem, as_of=as_of),
        "desk": desk_snapshot(mem, as_of=as_of),
        "calibrated_probability": False,
    }


@app.post("/v1/book/desk")
async def book_desk(
    payload: dict | None = None, session: Annotated[AsyncSession, Depends(get_session)] = None
) -> dict:
    """UNKNOWN queue + radars. Empty is empty."""
    from stinky_core.book import desk_snapshot

    mem, loaded, source = await _book_memory(payload, session)
    out = desk_snapshot(mem, as_of=(payload or {}).get("as_of"))
    out["source"] = source
    out["hydrated"] = loaded
    return out


@app.post("/v1/book/what-happened")
async def book_what_happened(
    payload: dict, session: Annotated[AsyncSession, Depends(get_session)]
) -> dict:
    """Post-detection path from stored ticks. Missing stays UNKNOWN."""
    from stinky_core.book import what_happened_next

    mem, loaded, source = await _book_memory(payload, session)
    mint = str(payload.get("mint") or "").strip()
    if not mint:
        return {"error": "mint required", "calibrated_probability": False, "source": source}
    out = what_happened_next(
        mem,
        mint=mint,
        t0=payload.get("t0") or payload.get("decision_timestamp") or payload.get("as_of"),
        as_of=payload.get("as_of"),
    )
    out["source"] = source
    out["hydrated"] = loaded
    return out


@app.post("/v1/book/recipe")
async def book_recipe(
    payload: dict, session: Annotated[AsyncSession, Depends(get_session)]
) -> dict:
    """Historical RUNNER recipe. Not a probability. Sample < 5 stays UNKNOWN."""
    from stinky_core.book import recipe_for

    mem, loaded, source = await _book_memory(payload, session)
    out = recipe_for(
        mem,
        payload.get("fingerprint"),
        as_of=payload.get("as_of") or payload.get("decision_timestamp"),
        exclude_mint=payload.get("exclude_mint") or payload.get("mint"),
        current=payload.get("current") if isinstance(payload.get("current"), dict) else None,
    )
    out["source"] = source
    out["hydrated"] = loaded
    return out


@app.post("/v1/book/observations")
async def book_observations(
    payload: dict | None = None, session: Annotated[AsyncSession, Depends(get_session)] = None
) -> dict:
    from stinky_core.book import observation_book

    mem, loaded, source = await _book_memory(payload, session)
    rows = observation_book(mem, as_of=(payload or {}).get("as_of"))
    return {
        "observations": rows,
        "count": len(rows),
        "source": source,
        "hydrated": loaded,
        "calibrated_probability": False,
    }


@app.post("/v1/book/insights")
async def book_insights(payload: dict | None = None) -> dict:
    """Candidate insights. Human review required. Never auto-tunes production."""
    from stinky_core.insights import candidate_insights

    body = payload or {}
    rows = body.get("dataset") if isinstance(body.get("dataset"), list) else []
    hold = body.get("holdout_mints") if isinstance(body.get("holdout_mints"), list) else []
    return candidate_insights(rows, holdout_mints=hold)


@app.post("/v1/book/quality")
async def book_quality(
    payload: dict | None = None, session: Annotated[AsyncSession, Depends(get_session)] = None
) -> dict:
    """Quality states for investigated mints. Empty is empty."""
    from stinky_core.quality_state import evaluate_book, QUALITY_VERSION

    mem, loaded, source = await _book_memory(payload, session)
    body = payload or {}
    rows = evaluate_book(mem, as_of=body.get("as_of"))
    mint = str(body.get("mint") or "").strip()
    if mint:
        rows = [r for r in rows if r.get("mint") == mint]
    return {
        "version": QUALITY_VERSION,
        "states": rows,
        "count": len(rows),
        "source": source,
        "hydrated": loaded,
        "calibrated_probability": False,
    }


@app.post("/v1/book/dips")
async def book_dips(
    payload: dict | None = None, session: Annotated[AsyncSession, Depends(get_session)] = None
) -> dict:
    """Active and resolved quality dips. Never invented."""
    from stinky_core.quality_state import evaluate_book, quality_dips, QUALITY_VERSION

    mem, loaded, source = await _book_memory(payload, session)
    body = payload or {}
    cards = quality_dips(evaluate_book(mem, as_of=body.get("as_of")))
    return {
        "version": QUALITY_VERSION,
        "dips": cards,
        "count": len(cards),
        "empty_note": "NO ACTIVE QUALITY DETERIORATION" if not cards else None,
        "source": source,
        "hydrated": loaded,
        "calibrated_probability": False,
    }


@app.post("/v1/book/slice-analogues")
async def book_slice_analogues(payload: dict, session: Annotated[AsyncSession, Depends(get_session)] = None) -> dict:
    """Age-aware analogues: T+offset compares only with T+offset."""
    from stinky_core.observation import slice_analogues

    mem, loaded, source = await _book_memory(payload, session)
    mint = str(payload.get("mint") or "").strip()
    if not mint:
        return {"error": "mint required", "calibrated_probability": False}
    out = slice_analogues(
        mem,
        mint=mint,
        offset_sec=int(payload.get("offset_sec") or 0),
        t0=payload.get("t0") or payload.get("decision_timestamp") or payload.get("as_of"),
        as_of=payload.get("as_of"),
    )
    out["source"] = source
    out["hydrated"] = loaded
    return out


@app.get("/v1/metrics")
async def metrics_endpoint() -> dict:
    from stinky_core.metrics import ENGINE_METRICS

    snap = ENGINE_METRICS.snapshot()
    snap["production_p95"] = "NOT MEASURED"
    from stinky_core.metrics import ENGINE_LOG

    snap["investigation_log"] = ENGINE_LOG.snapshot()
    return snap


@app.get("/v1/system/filter-stats")
async def filter_stats_endpoint() -> dict:
    from stinky_core.admission import FILTER_VERSION, filter_stats

    return {"filter_version": FILTER_VERSION, "stats": filter_stats.snapshot()}


def _probe_postgres(ok: bool, *, error: str | None = None, at: str | None = None) -> dict:
    return {
        "provider": "postgres",
        "at": at,
        "status": "UP" if ok else "DOWN",
        "ok": ok,
        "error": error,
        "source": "postgres",
    }


@app.get("/v1/operator")
async def operator_endpoint(session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    """Operator desk from persisted records. Empty is empty. Does not invent Gate 1."""
    from datetime import datetime, timezone

    from stinky_core.admission import GATE1_VOLUME_5M_USD, GATE1_VOLUME_CALIBRATION_MAX_USD
    from stinky_core.intelligence import INTEL_VERSION
    from stinky_core.memory import IntelligenceMemory
    from stinky_core.operator import OPERATOR_VERSION, count_live_gate1, operator_desk
    from sqlalchemy import text

    now = datetime.now(timezone.utc)
    db_ok: bool | None = None
    db_error: str | None = None
    last_read = None
    mem = IntelligenceMemory()
    source = "empty"
    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
        last_read = now
        mem, _loaded, source = await _book_memory(None, session)
        mem.record_provider_probe(_probe_postgres(True, at=now.isoformat()))
    except Exception as exc:
        db_ok = False
        db_error = f"{type(exc).__name__}: {exc}"[:200]
        mem.record_provider_probe(_probe_postgres(False, error=db_error, at=now.isoformat()))

    live_count = count_live_gate1(mem) if db_ok else None
    desk = operator_desk(
        mem,
        now=now,
        db={
            "connected": db_ok,
            "last_read_at": last_read,
            "error": db_error,
        },
        evidence_label_default="UNKNOWN",
        live_gate1_count=live_count,
        live_gate1_label="NOT OBSERVED" if db_ok and not live_count else ("UNKNOWN" if not db_ok else "OBSERVED"),
    )
    desk["intel_version"] = INTEL_VERSION
    desk["source"] = source
    desk["gate_status"]["threshold_usd"] = GATE1_VOLUME_5M_USD
    desk["gate_status"]["clamp_usd"] = GATE1_VOLUME_CALIBRATION_MAX_USD
    desk["operator_version"] = OPERATOR_VERSION
    return desk


@app.get("/v1/operator/investigations/{mint}")
async def operator_export(mint: str, session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    """Operator-readable investigation export from persisted data only."""
    from stinky_core.operator import export_investigation

    mem, loaded, source = await _book_memory(None, session)
    out = export_investigation(mem, mint=mint.strip(), evidence_label_default="UNKNOWN")
    out["source"] = source
    out["hydrated"] = loaded
    return out


@app.get("/v1/operator/trace/{mint}")
async def operator_trace(mint: str, session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    """Chronological investigation trace. Every line is a stored event."""
    from stinky_core.operator import build_trace, evidence_label

    mem, loaded, source = await _book_memory(None, session)
    events = build_trace(getattr(mem, "operator_events", []) or [], mint=mint.strip())
    return {
        "mint": mint.strip(),
        "source": source,
        "hydrated": loaded,
        "evidence_label": evidence_label(events[0].get("evidence_label") if events else None) if events else "UNKNOWN",
        "events": events,
        "count": len(events),
        "calibrated_probability": False,
        "note": "Empty trace means no operator events were persisted.",
    }


@app.get("/health")
async def health(session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    from sqlalchemy import text

    db_ok = False
    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    event_log = "unknown"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{settings.event_log_url.rstrip('/')}/health")
            if r.status_code >= 300:
                event_log = "degraded"
            else:
                body = r.json() if r.content else {}
                event_log = (
                    "ok"
                    if body.get("status") == "ok" and body.get("transport")
                    else "degraded"
                )
    except Exception:
        event_log = "down"

    status = "ok" if db_ok else "degraded"
    return {
        "status": status,
        "service": settings.service_name,
        "database": db_ok,
        "event_log": event_log,
        "live": db_ok,
    }





async def _trending_m5(
    *,
    min_volume_usd: float = 150_000.0,
    min_fees_sol: float = 1.0,
    limit: int = 30,
) -> list[dict]:
    """Pump-only trending: measured 5m volume >= Gate 1.

    Gate 1 is volume + protocol + mint. Unknown fees do NOT drop the row.
    """
    from sqlalchemy import text
    from stinky_api.db import SessionLocal

    async with SessionLocal() as session:
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        WITH high AS (
                          SELECT
                            ms.mint,
                            ms.volume_m5_usd,
                            ms.liquidity_usd,
                            ms.price_usd,
                            ms.market_cap_usd,
                            ms.fdv_usd,
                            ms.pair_address,
                            ms.dex_id,
                            ms.captured_at,
                            ROW_NUMBER() OVER (
                              PARTITION BY ms.mint
                              ORDER BY ms.captured_at DESC
                            ) AS rn
                          FROM market_snapshots ms
                          WHERE ms.volume_m5_usd IS NOT NULL
                            AND ms.volume_m5_usd >= :min_vol
                            AND lower(ms.mint) LIKE '%pump'
                        ),
                        fees AS (
                          SELECT DISTINCT ON (mint)
                            mint,
                            global_fees_sol,
                            global_fees_verified,
                            global_fees_source,
                            accepted,
                            rejection_reason
                          FROM filter_evaluations
                          ORDER BY mint, evaluated_at DESC
                        )
                        SELECT
                          h.mint,
                          h.volume_m5_usd,
                          h.liquidity_usd,
                          h.price_usd,
                          h.market_cap_usd,
                          h.fdv_usd,
                          h.pair_address,
                          h.dex_id,
                          h.captured_at,
                          f.global_fees_sol AS fees_sol,
                          f.global_fees_verified AS global_fees_verified,
                          f.global_fees_source AS global_fees_source,
                          f.accepted AS fees_accepted,
                          f.rejection_reason AS fees_rejection,
                          mt.creator,
                          mt.buyers_captured,
                          mt.migration_at,
                          mt.status AS track_status,
                          NULL::text AS name,
                          NULL::text AS symbol
                        FROM high h
                        LEFT JOIN migration_tracks mt ON mt.mint = h.mint
                        LEFT JOIN fees f ON f.mint = h.mint
                        WHERE h.rn = 1
                        ORDER BY h.volume_m5_usd DESC NULLS LAST
                        LIMIT :lim
                        """
                    ),
                    {
                        "min_vol": float(min_volume_usd),
                        "lim": int(max(limit * 3, 30)),
                    },
                )
            ).mappings().all()
        except Exception as exc:
            # Fallback without filter_evaluations join (table may be missing)
            logger.warning("trending.query_failed", error=str(exc)[:400])
            try:
                rows = (
                    await session.execute(
                        text(
                            """
                            WITH high AS (
                              SELECT
                                ms.mint,
                                ms.volume_m5_usd,
                                ms.liquidity_usd,
                                ms.price_usd,
                                ms.market_cap_usd,
                                ms.fdv_usd,
                                ms.pair_address,
                                ms.dex_id,
                                ms.captured_at,
                                ROW_NUMBER() OVER (
                                  PARTITION BY ms.mint
                                  ORDER BY ms.captured_at DESC
                                ) AS rn
                              FROM market_snapshots ms
                              WHERE ms.volume_m5_usd IS NOT NULL
                                AND ms.volume_m5_usd >= :min_vol
                                AND lower(ms.mint) LIKE '%pump'
                            )
                            SELECT
                              h.mint,
                              h.volume_m5_usd,
                              h.liquidity_usd,
                              h.price_usd,
                              h.market_cap_usd,
                              h.fdv_usd,
                              h.pair_address,
                              h.dex_id,
                              h.captured_at,
                              NULL::double precision AS fees_sol,
                              NULL::boolean AS global_fees_verified,
                              NULL::text AS global_fees_source,
                              NULL::boolean AS fees_accepted,
                              NULL::text AS fees_rejection,
                              mt.creator,
                              mt.buyers_captured,
                              mt.migration_at,
                              mt.status AS track_status,
                              NULL::text AS name,
                              NULL::text AS symbol
                            FROM high h
                            LEFT JOIN migration_tracks mt ON mt.mint = h.mint
                            WHERE h.rn = 1
                            ORDER BY h.volume_m5_usd DESC NULLS LAST
                            LIMIT :lim
                            """
                        ),
                        {
                            "min_vol": float(min_volume_usd),
                            "lim": int(max(limit * 3, 30)),
                        },
                    )
                ).mappings().all()
            except Exception as exc2:
                logger.warning("trending.query_failed_fallback", error=str(exc2)[:400])
                return []

        out = []
        for r in rows:
            d = dict(r)
            mint = str(d.get("mint") or "")
            # Strict pump mint suffix (no dex_id side-door)
            if not mint.lower().endswith("pump"):
                continue
            for k in ("captured_at", "migration_at"):
                if d.get(k) is not None and hasattr(d[k], "isoformat"):
                    d[k] = d[k].isoformat()
            for k in (
                "volume_m5_usd",
                "liquidity_usd",
                "price_usd",
                "market_cap_usd",
                "fdv_usd",
                "fees_sol",
            ):
                if d.get(k) is not None:
                    try:
                        d[k] = float(d[k])
                    except (TypeError, ValueError):
                        d[k] = None
            # Gate 1 via canonical engine. Unknown fees do not drop the row.
            gated = queries.apply_canonical_gate(
                {
                    **d,
                    "protocol": d.get("dex_id") or "pumpfun",
                    "global_fees_sol": d.get("fees_sol"),
                    "global_fees_verified": d.get("global_fees_verified"),
                    "global_fees_source": d.get("global_fees_source"),
                    "migrated": True,
                    "tab": "migrated",
                },
                min_fees_sol=float(min_fees_sol) if min_fees_sol else 1.0,
            )
            if not gated.get("eligible"):
                continue
            d["global_fees_paid_sol"] = gated.get("global_fees_sol")
            d["global_fees_sol"] = gated.get("global_fees_sol")
            d["global_fees_verified"] = bool(gated.get("global_fees_verified"))
            d["eligible"] = True
            d["rejection_reason"] = None
            d["reason_codes"] = gated.get("reason_codes") or []
            d["filter_version"] = gated.get("filter_version")
            out.append(d)
            if len(out) >= limit:
                break
        return out



@app.get("/v1/command-center")
async def command_center() -> dict:
    """Home feed ? each section uses its own DB session so one timeout cannot poison the rest."""
    import asyncio
    from sqlalchemy import text
    from stinky_api.db import SessionLocal

    async def _safe(label: str, coro_factory, default, timeout: float = 4.0):
        try:
            return await asyncio.wait_for(coro_factory(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("command_center.section_failed", section=label, error="timeout")
            return default
        except Exception as exc:
            logger.warning(
                "command_center.section_failed",
                section=label,
                error=f"{type(exc).__name__}: {exc}"[:240],
            )
            return default

    async def _counts():
        async with SessionLocal() as session:
            out: dict = {}
            for key, sql in (
                ("migrations", "SELECT COUNT(*)::int FROM events WHERE event_type='token.migrated'"),
                ("tracks", "SELECT COUNT(*)::int FROM migration_tracks"),
                ("launches", "SELECT COUNT(*)::int FROM events WHERE event_type='token.launch'"),
                ("entities", "SELECT COUNT(*)::int FROM entities"),
                ("wallets", "SELECT COUNT(*)::int FROM wallet_performance"),
                ("buyers", "SELECT COUNT(*)::int FROM migration_buyers"),
                ("alerts", "SELECT COUNT(*)::int FROM events WHERE event_type='alert.candidate'"),
            ):
                try:
                    out[key] = (await session.execute(text(sql))).scalar() or 0
                except Exception:
                    out[key] = 0
            return out

    async def _runners():
        """Opportunity runners from fee-gated alert.candidate only (no live HTTP)."""
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT DISTINCT ON (payload->>'mint')
                          payload->>'mint' AS mint,
                          payload->>'name' AS name,
                          payload->>'symbol' AS symbol,
                          payload->>'creator' AS creator,
                          payload->>'pool' AS pool,
                          (payload->>'volume_m5_usd')::float AS volume_m5_usd,
                          (payload->>'liquidity_usd')::float AS liquidity_usd,
                          (payload->>'stinky_score')::float AS stinky_score,
                          (payload->>'confidence')::float AS confidence,
                          (payload->>'fees_sol')::float AS fees_sol,
                          (payload->>'global_fees_paid_sol')::float AS global_fees_paid_sol,
                          (payload->>'global_fees_verified')::boolean AS global_fees_verified,
                          (payload->>'meaningful_buyer_count')::int AS meaningful_buyer_count,
                          (payload->>'early_buyer_count')::int AS early_buyer_count,
                          occurred_at AS migration_at
                        FROM events
                        WHERE event_type = 'alert.candidate'
                          AND payload->>'mint' IS NOT NULL
                        ORDER BY payload->>'mint', occurred_at DESC
                        """
                    )
                )
            ).mappings().all()
            out = []
            min_fees = 1.0
            for r in rows:
                d = dict(r)
                fees = d.get("global_fees_paid_sol")
                if fees is None:
                    fees = d.get("fees_sol")
                try:
                    ff = float(fees) if fees is not None else None
                except (TypeError, ValueError):
                    ff = None
                gated = queries.apply_canonical_gate(
                    {
                        **d,
                        "fees_sol": ff,
                        "global_fees_sol": ff,
                        "global_fees_verified": d.get("global_fees_verified"),
                        "protocol": "pumpfun",
                    },
                    min_fees_sol=min_fees,
                )
                if not gated.get("eligible"):
                    continue
                if d.get("migration_at") is not None and hasattr(d["migration_at"], "isoformat"):
                    d["migration_at"] = d["migration_at"].isoformat()
                d["fees_sol"] = ff
                d["global_fees_paid_sol"] = ff
                d["status"] = "alerted"
                d["eligible"] = True
                d["rejection_reason"] = None
                d["reason_codes"] = gated.get("reason_codes") or []
                out.append(d)
            out.sort(key=lambda x: x.get("migration_at") or "", reverse=True)
            return out[:20]

    async def _alerts():
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT event_id::text,
                               occurred_at,
                               payload->>'mint' AS mint,
                               payload->>'name' AS name,
                               payload->>'symbol' AS symbol,
                               payload->>'creator' AS creator,
                               (payload->>'volume_m5_usd')::float AS volume_m5_usd,
                               (payload->>'stinky_score')::float AS stinky_score,
                               (payload->>'confidence')::float AS confidence,
                               (payload->>'meaningful_buyer_count')::int AS meaningful_buyer_count
                        FROM events
                        WHERE event_type = 'alert.candidate'
                        ORDER BY occurred_at DESC
                        LIMIT 20
                        """
                    )
                )
            ).mappings().all()
            out = []
            for r in rows:
                d = dict(r)
                if d.get("occurred_at") is not None:
                    d["occurred_at"] = d["occurred_at"].isoformat()
                out.append(d)
            return out

    async def _entities():
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT entity_id::text, entity_type, display_label, primary_wallet,
                               wallet_count, launch_count, early_buy_count, confidence
                        FROM entities
                        ORDER BY launch_count DESC NULLS LAST
                        LIMIT 10
                        """
                    )
                )
            ).mappings().all()
            return [dict(r) for r in rows]

    async def _wallets():
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT wallet, early_buy_count, total_buys, total_sells,
                               hit_rate, avg_return_pct
                        FROM wallet_performance
                        WHERE early_buy_count > 0
                        ORDER BY early_buy_count DESC NULLS LAST
                        LIMIT 15
                        """
                    )
                )
            ).mappings().all()
            return [dict(r) for r in rows]

    async def _pipeline():
        async with SessionLocal() as session:
            stats = {}
            for key, sql in (
                ("migration_tracks", "SELECT COUNT(*)::int FROM migration_tracks"),
                ("migration_buyers", "SELECT COUNT(*)::int FROM migration_buyers"),
                ("entities", "SELECT COUNT(*)::int FROM entities"),
                ("alert_log", "SELECT COUNT(*)::int FROM alert_log"),
                ("wallet_early_success", "SELECT COUNT(*)::int FROM wallet_early_success"),
                (
                    "token_migrated_events",
                    "SELECT COUNT(*)::int FROM events WHERE event_type='token.migrated'",
                ),
            ):
                try:
                    stats[key] = (await session.execute(text(sql))).scalar() or 0
                except Exception:
                    stats[key] = None
            return {"available": True, "tables": stats, "maintain_last_utc": None}

    async def _precision():
        async with SessionLocal() as session:
            try:
                rows = (
                    await session.execute(
                        text(
                            """
                            SELECT outcome, COUNT(*)::int AS n
                            FROM alert_outcomes
                            GROUP BY outcome
                            """
                        )
                    )
                ).mappings().all()
            except Exception:
                return {"available": False, "counts": {}, "message": "no alert_outcomes"}
            counts = {r["outcome"]: r["n"] for r in rows}
            total = sum(counts.values()) or 0
            runners = counts.get("runner", 0) + counts.get("mega_runner", 0)
            return {
                "available": True,
                "counts": counts,
                "total": total,
                "runner_rate": (runners / total) if total else None,
                "runners": runners,
                "fade": counts.get("fade", 0),
                "held": counts.get("held", 0) + counts.get("mid", 0),
            }

    # Run independent sections concurrently (each has own session)
    c, runners, alerts, entities, wallets, pipeline, alert_precision, trending = await asyncio.gather(
        _safe("counts", _counts, {}, 6.0),
        _safe("runners", _runners, [], 6.0),
        _safe("alerts", _alerts, [], 6.0),
        _safe("entities", _entities, [], 6.0),
        _safe("wallets", _wallets, [], 6.0),
        _safe("pipeline", _pipeline, {"available": False, "tables": {}}, 6.0),
        _safe("alert_precision", _precision, {"available": False, "counts": {}}, 6.0),
        _safe("trending", lambda: _trending_m5(min_volume_usd=150_000.0, min_fees_sol=1.0, limit=25), [], 8.0),
    )

    opportunity = []
    for a in alerts or []:
        score = a.get("stinky_score")
        try:
            if score is None or float(score) < 55:
                continue
        except (TypeError, ValueError):
            continue
        opportunity.append(
            {
                "mint": a.get("mint"),
                "name": a.get("name"),
                "symbol": a.get("symbol"),
                "score": a.get("stinky_score"),
                "confidence": a.get("confidence"),
                "volume_m5_usd": a.get("volume_m5_usd"),
                "meaningful_buyer_count": a.get("meaningful_buyer_count"),
            }
        )

    return {
        "status": "live",
        "counts": c or {},
        "pipeline": pipeline,
        "runners": runners or [],
        "alerts": alerts or [],
        "entities": entities or [],
        "smart_wallets": wallets or [],
        "launches": [],
        "opportunity_queue": opportunity[:12],
        "trending": {
            "available": True,
            "min_volume_m5_usd": 150000,
            "engine": "trending-v1.0.0-volume-first",
            "message": "Gate 1: latest measured 5m volume >= $150k. Investigation trigger, not a buy signal. Fees optional evidence.",
            "items": trending or [],
            "count": len(trending or []),
        },
        "patterns": {
            "available": True,
            "items": [],
            "message": "open Patterns page for full discovery",
        },
        "alert_precision": alert_precision,
    }




@app.get("/v1/trending")
async def trending(
    min_volume_usd: float = Query(150_000.0, ge=0.0),
    min_fees_sol: float = Query(1.0, ge=0.0),
    limit: int = Query(30, ge=1, le=100),
) -> dict:
    """Trending by measured 5m volume — Gate 1 investigation trigger."""
    items = await _trending_m5(
        min_volume_usd=min_volume_usd,
        min_fees_sol=min_fees_sol,
        limit=limit,
    )
    return {
        "available": True,
        "min_volume_m5_usd": min_volume_usd,
        "min_fees_sol": min_fees_sol,
        "engine": "trending-v1.0.0-volume-first",
        "items": items,
        "count": len(items),
    }

@app.get("/v1/runners")
async def runners(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(50, ge=1, le=200),
    min_fees_sol: float = Query(1.0, ge=0.0),
    min_volume_m5_usd: float = Query(150_000.0, ge=0.0),
    enrich_fees: bool = Query(False),
    pump_only: bool = Query(True),
) -> dict:
    """Live runners: Gate 1 volume-first (5m >= $150k). Fees are optional evidence."""
    items = await queries.recent_migrations(
        session,
        limit=limit,
        min_fees_sol=min_fees_sol,
        min_volume_m5_usd=min_volume_m5_usd,
        pump_only=pump_only,
        enrich_fees=enrich_fees,
    )
    return {"items": items, "count": len(items), "min_fees_sol": min_fees_sol, "min_volume_m5_usd": min_volume_m5_usd}


@app.get("/v1/alerts")
async def alerts(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    rows = await queries.recent_alerts(session, limit=limit)
    return {"items": rows, "count": len(rows)}


@app.get("/v1/entities")
async def entities(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    rows = await queries.top_entities(session, limit=limit)
    return {"items": rows, "count": len(rows)}


@app.get("/v1/wallets/smart")
async def smart_wallets(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """Wallets worth watching ? ranked with explainable why_watch from measured stats."""
    rows = await queries.wallets_worth_watching(session, limit=limit)
    return {"items": rows, "count": len(rows)}


@app.get("/v1/wallets/success")
async def wallets_success(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(30, ge=1, le=100),
) -> dict:
    """Top early buyers by measured success on labeled runner tokens."""
    from sqlalchemy import text as sa_text

    try:
        rows = (
            await session.execute(
                sa_text(
                    """
                    SELECT wallet, early_entries, early_on_mega, early_on_runner,
                           early_on_mid, early_on_fade, success_rate, sample_size,
                           last_success_at, updated_at
                    FROM wallet_early_success
                    WHERE sample_size >= 1
                    ORDER BY success_rate DESC NULLS LAST,
                             early_on_mega DESC,
                             early_on_runner DESC,
                             sample_size DESC
                    LIMIT :lim
                    """
                ),
                {"lim": limit},
            )
        ).mappings().all()
        return {
            "available": True,
            "engine": "success-learn-v0.2",
            "items": [dict(r) for r in rows],
            "count": len(rows),
        }
    except Exception as exc:
        return {
            "available": False,
            "engine": "success-learn-v0.2",
            "message": f"wallet_early_success not ready: {exc}",
            "items": [],
            "count": 0,
        }


@app.post("/v1/learn/success")
async def learn_success(
    token_limit: int = Query(2000, ge=10, le=10000),
) -> dict:
    """Recompute token_outcomes + wallet_early_success from measured snapshots.

    Prefer CLI on collector host: stinky-collector learn-success
    This endpoint invokes the same learner when the package is installed.
    """
    try:
        from post_migration.learn import SuccessLearner
    except ImportError:
        return {
            "available": False,
            "engine": "success-learn-v0.2",
            "message": "post_migration.learn not installed ? run: stinky-collector learn-success",
        }

    learner = SuccessLearner()
    try:
        result = await learner.run_full(token_limit=token_limit)
        return {
            "available": True,
            "engine": "success-learn-v0.2",
            **(result if isinstance(result, dict) else {"result": result}),
        }
    except Exception as exc:
        return {
            "available": False,
            "engine": "success-learn-v0.2",
            "error": str(exc)[:300],
        }
    finally:
        try:
            await learner.close()
        except Exception:
            pass


@app.get("/v1/wallets/{address}")
async def wallet_detail(
    address: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    detail = await queries.wallet_detail(session, address)
    if not detail:
        return {
            "available": False,
            "wallet": address,
            "message": "No stored performance, early buys, or trades for this wallet",
        }
    return {"available": True, **detail}


@app.get("/v1/entities/multi-wallet")
async def entities_multi_wallet(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(30, ge=1, le=100),
) -> dict:
    """Entities that already have more than one linked wallet (post safe-merge)."""
    rows = await queries.multi_wallet_entities(session, limit=limit)
    return {"items": rows, "count": len(rows)}


@app.get("/v1/entities/{entity_id}")
async def entity_detail(
    entity_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    detail = await queries.entity_detail(session, entity_id)
    if not detail:
        return {
            "available": False,
            "entity_id": entity_id,
            "message": "Entity not found",
        }
    return {"available": True, **detail}


@app.get("/v1/tokens/{mint}")
async def token_detail(
    mint: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    detail = await queries.mint_detail(session, mint)
    if not detail:
        return {
            "available": False,
            "mint": mint,
            "message": "No stored intelligence for this mint yet",
        }
    return {"available": True, **detail}


@app.get("/v1/search")
async def search(
    session: Annotated[AsyncSession, Depends(get_session)],
    q: str = Query("", min_length=0),
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    return await queries.search_all(session, q, limit=limit)


@app.get("/v1/patterns")
async def patterns(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(25, ge=1, le=100),
) -> dict:
    """Deterministic pattern discovery over stored intelligence."""
    return await queries.discover_patterns(session, limit=limit)


@app.get("/v1/graph")
async def graph(
    session: Annotated[AsyncSession, Depends(get_session)],
    min_shared: int = Query(2, ge=1, le=20),
    edge_limit: int = Query(80, ge=10, le=300),
) -> dict:
    """Relationship graph: co-buy edges + multi-wallet entity links."""
    return await queries.graph_overview(
        session, min_shared=min_shared, edge_limit=edge_limit
    )


@app.get("/v1/graph/wallet/{address}")
async def graph_wallet(
    address: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    min_shared: int = Query(1, ge=1, le=20),
) -> dict:
    detail = await queries.graph_ego(session, address, min_shared=min_shared)
    if not detail:
        return {
            "available": False,
            "wallet": address,
            "message": "No co-buy neighbors or early entries for this wallet",
        }
    return detail


@app.get("/v1/time-machine/wallet/{address}")
async def time_machine_wallet(
    address: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Activity timeline for a wallet from measured events only."""
    detail = await queries.time_machine_wallet(session, address)
    if not detail:
        return {
            "available": False,
            "wallet": address,
            "message": "No launches, early buys, or trades stored for this wallet",
        }
    return detail


@app.get("/v1/time-machine/entity/{entity_id}")
async def time_machine_entity(
    entity_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Merged timeline across all wallets on an entity."""
    detail = await queries.time_machine_entity(session, entity_id)
    if not detail:
        return {
            "available": False,
            "entity_id": entity_id,
            "message": "Entity not found or no linked activity",
        }
    return detail


@app.get("/v1/research")
async def research(
    session: Annotated[AsyncSession, Depends(get_session)],
    q: str = Query("", max_length=500),
    preset: str | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
) -> dict:
    """Deterministic research over measured intelligence ? no invented answers."""
    return await queries.research_query(
        session, q=q, preset=preset, limit=limit
    )


@app.get("/v1/outcomes")
async def outcomes(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(50, ge=1, le=200),
    recompute: bool = Query(True),
) -> dict:
    """Alert precision: gated DMs measured against post-alert market snapshots."""
    return await queries.alert_outcomes(session, limit=limit, recompute=recompute)


@app.post("/v1/scores/backfill")
async def scores_backfill(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(5000, ge=1, le=50000),
) -> dict:
    """One-shot seed of score_snapshots from historical scored events."""
    return await queries.backfill_score_snapshots_from_events(session, limit=limit)


@app.get("/v1/scores/{subject_type}/{subject_id}")
async def scores_series(
    subject_type: str,
    subject_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Measured score history for wallet | entity | mint."""
    if subject_type not in ("wallet", "entity", "mint"):
        return {
            "available": False,
            "items": [],
            "message": "subject_type must be wallet|entity|mint",
        }
    items = await queries.score_series_for_subject(
        session, subject_type=subject_type, subject_id=subject_id
    )
    return {
        "available": True,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "count": len(items),
        "items": items,
    }


@app.get("/v1/replay/funnel")
async def replay_funnel(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Migration ? track ? buyers ? alert funnel (measured counts)."""
    return await queries.replay_funnel(session)


@app.get("/v1/replay/backtest")
async def replay_backtest(
    session: Annotated[AsyncSession, Depends(get_session)],
    min_score: float = Query(55.0, ge=0, le=100),
    limit: int = Query(200, ge=1, le=2000),
) -> dict:
    """Score-gate backtest against market_snapshots."""
    return await queries.replay_score_gate_backtest(
        session, min_score=min_score, limit=limit
    )


@app.get("/v1/outcomes/tokens")
async def token_outcomes_list(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(50, ge=1, le=200),
    label: str | None = Query(None),
) -> dict:
    """Labeled migration outcomes from market_snapshots peaks."""
    from sqlalchemy import text as sa_text

    try:
        if label:
            rows = (
                await session.execute(
                    sa_text(
                        """
                        SELECT mint, label, peak_volume_m5_usd, peak_market_cap_usd,
                               peak_liquidity_usd, snapshots_n, evaluated_at, notes
                        FROM token_outcomes
                        WHERE label = :lab
                        ORDER BY evaluated_at DESC
                        LIMIT :lim
                        """
                    ),
                    {"lim": limit, "lab": label},
                )
            ).mappings().all()
        else:
            rows = (
                await session.execute(
                    sa_text(
                        """
                        SELECT mint, label, peak_volume_m5_usd, peak_market_cap_usd,
                               peak_liquidity_usd, snapshots_n, evaluated_at, notes
                        FROM token_outcomes
                        ORDER BY evaluated_at DESC
                        LIMIT :lim
                        """
                    ),
                    {"lim": limit},
                )
            ).mappings().all()
        counts = {}
        try:
            crows = (
                await session.execute(
                    sa_text(
                        "SELECT label, COUNT(*)::int AS n FROM token_outcomes GROUP BY label"
                    )
                )
            ).mappings().all()
            counts = {r["label"]: r["n"] for r in crows}
        except Exception:
            pass
        return {
            "available": True,
            "engine": "success-learn-v0.1",
            "counts": counts,
            "items": [dict(r) for r in rows],
        }
    except Exception as exc:
        return {"available": False, "message": str(exc), "items": [], "counts": {}}


@app.get("/v1/watchlist")
async def watchlist_get(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """User/operator watchlist ? mints and wallets (durable Postgres)."""
    from sqlalchemy import text as sa_text
    await session.execute(
        sa_text(
            """
            CREATE TABLE IF NOT EXISTS stinky_watchlist (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                kind TEXT NOT NULL CHECK (kind IN ('wallet', 'mint')),
                address TEXT NOT NULL,
                note TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (kind, address)
            )
            """
        )
    )
    await session.commit()
    rows = (
        await session.execute(
            sa_text(
                """
                SELECT id::text, kind, address, note, created_at
                FROM stinky_watchlist
                ORDER BY created_at DESC
                LIMIT :lim
                """
            ),
            {"lim": limit},
        )
    ).mappings().all()
    return {"items": [dict(r) for r in rows], "count": len(rows)}


@app.post("/v1/watchlist")
async def watchlist_add(
    session: Annotated[AsyncSession, Depends(get_session)],
    kind: str = Query(..., pattern="^(wallet|mint)$"),
    address: str = Query(..., min_length=8, max_length=128),
    note: str | None = Query(None, max_length=200),
) -> dict:
    from sqlalchemy import text as sa_text
    address = address.strip()
    await session.execute(
        sa_text(
            """
            CREATE TABLE IF NOT EXISTS stinky_watchlist (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                kind TEXT NOT NULL CHECK (kind IN ('wallet', 'mint')),
                address TEXT NOT NULL,
                note TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (kind, address)
            )
            """
        )
    )
    await session.execute(
        sa_text(
            """
            INSERT INTO stinky_watchlist (kind, address, note)
            VALUES (:k, :a, :n)
            ON CONFLICT (kind, address) DO UPDATE SET note = COALESCE(EXCLUDED.note, stinky_watchlist.note)
            """
        ),
        {"k": kind, "a": address, "n": note},
    )
    await session.commit()
    return {"ok": True, "kind": kind, "address": address}


@app.delete("/v1/watchlist")
async def watchlist_remove(
    session: Annotated[AsyncSession, Depends(get_session)],
    kind: str = Query(..., pattern="^(wallet|mint)$"),
    address: str = Query(..., min_length=8, max_length=128),
) -> dict:
    from sqlalchemy import text as sa_text
    address = address.strip()
    await session.execute(
        sa_text(
            "DELETE FROM stinky_watchlist WHERE kind = :k AND address = :a"
        ),
        {"k": kind, "a": address},
    )
    await session.commit()
    return {"ok": True, "kind": kind, "address": address}

