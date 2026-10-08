"""Bounded evidence details; no adequacy recomputation or experiment writes."""
from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from statistics import median
import sys

from fastapi import APIRouter, Depends
from sqlalchemy import text
from stinky_api.db import get_session
from stinky_api.intelligence_execution_v2 import AUTHORITY

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
import audit_intelligence_execution_v2_health as health

v2 = health.v2
router = APIRouter(prefix="/v1/intelligence", tags=["intelligence"])
LIMIT = 500
SOURCE_LIMIT = 20
LOG_BYTES = 1_000_000


def distribution(values, total):
    values = sorted(values)
    return {"n": len(values), "unavailable": total-len(values),
            "median_sec": median(values) if values else None,
            "p90_sec": values[math.ceil(.9*len(values))-1] if values else None,
            "max_sec": max(values) if values else None}


def summarize_details(rows, registry, as_of, truncated=False):
    v2.verify_registry(registry)
    v2.summarize(rows)  # Integrity validation only; subset adequacy is never exposed.
    counts, reasons, metrics = Counter(), Counter(), defaultdict(list)
    sessions, missing_windows, latest_entry, latest_exit, recordings = set(), [], [], [], []
    pending_maturity = pending_overdue = 0
    for row in rows:
        plan = v2.decode(row["plan"])
        result = v2.decode(row["result"]) if row["result"] is not None else None
        if v2.dt(plan["prospective_boundary"]) != registry["prospective_boundary"] or v2.dt(plan["planned_at"]) > as_of:
            raise ValueError("boundary_or_clock_mismatch")
        for payload in (plan, result):
            if payload is not None and any(payload.get(k) is not value for k, value in v2.AUTHORITY.items()):
                raise ValueError("unsafe_evidence")
        v2.evaluate(plan, [], as_of)  # Also validates pending plan schedule.
        entry, exit_at = v2.dt(plan["entry_target"]), v2.dt(plan["exit_target"])
        maturity = exit_at+timedelta(seconds=v2.policy()["observation_tolerance_sec"])
        status = result["status"] if result else "PENDING"
        counts[status] += 1
        metrics["decision_to_admission"].append((v2.dt(plan["planned_at"])-v2.dt(plan["decided_at"])).total_seconds())
        if result:
            recorded = row["recorded_at"]
            if recorded != v2.dt(result["as_of"]) or recorded > as_of or recorded < maturity:
                raise ValueError("invalid_recording_clock")
            recordings.append(recorded)
            metrics["maturity_to_recording"].append((recorded-maturity).total_seconds())
            if result.get("reason"):
                reasons[(status, result["reason"])] += 1
            session = plan.get("runtime_session")
            if session and session.get("identity_verified") is True:
                sessions.add(session["started_at"])
        else:
            pending_maturity += int(as_of < maturity)
            pending_overdue += int(as_of >= maturity)
        if status == "PAPER_PRICED":
            a, b = v2.dt(result["entry"]["captured_at"]), v2.dt(result["exit"]["captured_at"])
            latest_entry.append(a)
            latest_exit.append(b)
            metrics["entry_observation_delay"].append((a-entry).total_seconds())
            metrics["exit_observation_delay"].append((b-exit_at).total_seconds())
        elif result and result.get("reason") in {"entry_observation_missing", "exit_observation_missing"}:
            phase = "entry" if result["reason"] == "entry_observation_missing" else "exit"
            missing_windows.append({"plan_id": row["id"], "status": status, "reason": result["reason"],
                                    "target": plan[f"{phase}_target"], "phase": phase})
    total = len(rows)
    return {"status": "OBSERVED", "as_of": as_of.isoformat(), "policy_version": v2.VERSION,
            "policy_sha256": registry["policy_sha256"], "prospective_boundary": registry["prospective_boundary"].isoformat(),
            "scope": {"sampled_plans": total, "plan_limit": LIMIT, "truncated": truncated, "selection": "LATEST_PLAN_IDS"},
            "counts": {s: counts[s] for s in ("PAPER_PRICED", "UNKNOWN", "REJECTED", "PENDING")},
            "reasons": [{"status": s, "reason": r, "count": n} for (s, r), n in sorted(reasons.items())],
            "bound_observations": {"entry": len(latest_entry), "exit": len(latest_exit), "unavailable": total-len(latest_entry)},
            "latency": {k: distribution(metrics[k], total) for k in ("detection_to_admission", "decision_to_admission",
                "entry_observation_delay", "exit_observation_delay", "maturity_to_recording")},
            "quantile_method": "NEAREST_RANK_P90", "freshness_threshold_sec": 300,
            "freshness": {"bound_entry": health.freshness(max(latest_entry, default=None), as_of, 300),
                "bound_exit": health.freshness(max(latest_exit, default=None), as_of, 300),
                "terminal_recording": health.freshness(max(recordings, default=None), as_of, 300)},
            "pending": {"awaiting_maturity": pending_maturity, "mature_without_result": pending_overdue},
            "session_starts": sorted(sessions), "session_ends": "UNAVAILABLE", "worker_downtime": "UNESTABLISHED",
            "missing_windows": missing_windows[:SOURCE_LIMIT], "missing_windows_truncated": len(missing_windows) > SOURCE_LIMIT,
            **AUTHORITY}


def local_support(as_of):
    logs = {name: health.log_support(ROOT / f"logs/{name}.log", as_of, LOG_BYTES) for name in ("collector", "maintain")}
    heartbeats = {}
    for name in ("collector", "maintain"):
        try:
            with (ROOT / f"logs/runtime-state-{name}.json").open("rb") as stream:
                state = json.loads(stream.read(16_384))
            heartbeats[name] = health.runtime_health(state, False, as_of, 180)
        except (OSError, ValueError, TypeError):
            heartbeats[name] = {"status": "UNAVAILABLE", "identity_verified": False}
    return logs, heartbeats


async def operator_details(session):
    try:
        async with asyncio.timeout(5):
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            await session.execute(text("SET LOCAL statement_timeout = '2000ms'"))
            as_of = (await session.execute(text("SELECT clock_timestamp()"))).scalar_one()
            registry = (await session.execute(text("SELECT * FROM intelligence_execution_v2_registry WHERE policy_version=:version"),
                                                  {"version": v2.VERSION})).mappings().one()
            rows = (await session.execute(text("""SELECT p.id,p.mint,p.plan,p.plan_sha256,r.result,r.result_sha256,r.recorded_at
                FROM intelligence_execution_v2_plans p LEFT JOIN intelligence_execution_v2_results r ON r.plan_id=p.id
                WHERE p.policy_version=:version ORDER BY p.id DESC LIMIT :limit"""),
                {"version": v2.VERSION, "limit": LIMIT+1})).mappings().all()
            detail = summarize_details(rows[:LIMIT], registry, as_of, len(rows) > LIMIT)
            mints = sorted({row["mint"] for row in rows[:LIMIT]})
            capture = (await session.execute(text("""SELECT max(s.captured_at) FROM unnest(CAST(:mints AS text[])) m(mint)
                CROSS JOIN LATERAL (SELECT captured_at FROM market_snapshots WHERE mint=m.mint AND captured_at<=:as_of
                    ORDER BY captured_at DESC LIMIT 1) s"""), {"mints": mints, "as_of": as_of})).scalar_one()
            detail["freshness"]["selected_mint_capture"] = health.freshness(capture, as_of, 300)
            detail["capture_mint_scope"] = len(mints)
            # At most 20 indexed mint/time windows, each capped at 101 captures.
            coverage = []
            by_id = {row["id"]: row for row in rows[:LIMIT]}
            for window in detail["missing_windows"]:
                row = by_id[window["plan_id"]]
                target = v2.dt(window["target"])
                samples = (await session.execute(text("""SELECT captured_at,price_usd FROM market_snapshots
                    WHERE mint=:mint AND captured_at BETWEEN :start AND :end AND captured_at<=:as_of
                    ORDER BY captured_at LIMIT 101"""), {"mint": row["mint"], "start": target-timedelta(seconds=120),
                    "end": target+timedelta(seconds=150), "as_of": as_of})).mappings().all()
                support = health.window_support([s["captured_at"] for s in samples[:100]], target, as_of)
                coverage.append({**window, **support, "capture_limit": 100, "truncated": len(samples) > 100})
            detail["source_coverage"] = coverage
            detail["source_coverage_limit"] = SOURCE_LIMIT
        logs, heartbeats = await asyncio.to_thread(local_support, datetime.now(timezone.utc))
        detail["collection"] = {"heartbeats": heartbeats, "logs": {name: {k: value for k, value in log.items()
            if k != "timestamped_events"} for name, log in logs.items()}, "log_byte_limit": LOG_BYTES}
        correlations = []
        for window in coverage:
            start, end = v2.dt(window["target"]), v2.dt(window["window_end"])
            covered = all(log.get("earliest_timestamp") and log.get("latest_timestamp")
                and v2.dt(log["earliest_timestamp"]) <= start and v2.dt(log["latest_timestamp"]) >= end for log in logs.values())
            n = sum(1 for log in logs.values() for e in log["timestamped_events"]
                    if e["category"] == "provider_rate_limit" and start <= v2.dt(e["at"]) <= end)
            correlations.append({"plan_id": window["plan_id"], "rate_limit_lines": n if covered else None,
                                 "retained_window_covered": covered, "causal": False})
        detail["rate_limit_correlations"] = correlations
        detail["limitations"] = ["Latest-plan sample only; summary adequacy is unchanged.",
            "Bound observations/latencies are available only for PAPER_PRICED; unpriced clocks remain unavailable.",
            "Current captures are supporting coverage, not historical ingestion or outcome reclassification.",
            "Log correlations are service-wide, noncausal and limited to retained timestamp ranges.",
            "Heartbeats have no live process-identity proof here; no continuous coverage or downtime inferred."]
        return detail
    except Exception:
        await session.rollback()
        return {"status": "UNAVAILABLE", "reason": "connection_or_evidence_validation_failed", **AUTHORITY}


@router.get("/execution-v2/details")
async def endpoint(session=Depends(get_session)):
    return await operator_details(session)
