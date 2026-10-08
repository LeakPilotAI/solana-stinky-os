"""Read-only retained supervisor observations, never experiment/session evidence."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import json
from fastapi import APIRouter, Depends
from sqlalchemy import text
from stinky_api.db import get_session
from stinky_api.intelligence_execution_v2 import AUTHORITY, POLICY_VERSION
from stinky_api.intelligence_execution_v2_details import ROOT, health
from genesis_pass_provenance import read_observations

router = APIRouter(prefix="/v1/intelligence", tags=["intelligence"])


def summarize_passes(source, state, as_of):
    if source["status"] != "OBSERVED" or source.get("invalid_lines", 0) or source.get("conflicting_event_ids", 0):
        return {"status": "UNAVAILABLE", "reason": "missing_or_invalid_pass_evidence", **AUTHORITY}
    grouped = {}
    for event in source["events"]:
        group = grouped.setdefault(event["pass_id"], {})
        if group and any(old["observer_id"] != event["observer_id"] or old["supervisor_pid"] != event["supervisor_pid"] for old in group.values()):
            raise ValueError("conflicting_pass_identity")
        if event["phase"] == "START" and (event["elapsed_sec"] is not None or event["return_code"] is not None or event["wall_clock_order"] != "UNAVAILABLE"):
            raise ValueError("invalid_start")
        if event["phase"] in group or (event["phase"] in {"FINISH", "RAISED"} and any(k in group for k in ("FINISH", "RAISED"))):
            raise ValueError("conflicting_phase")
        group[event["phase"]] = event
    passes = []
    for pass_id, group in grouped.items():
        start = group.get("START")
        finish = group.get("FINISH") or group.get("RAISED")
        e = start or finish
        a, b = start["observed_at"] if start else None, finish["observed_at"] if finish else None
        order = finish["wall_clock_order"] if finish else "UNAVAILABLE"
        if a and b and order != ("REGRESSION" if datetime.fromisoformat(b) < datetime.fromisoformat(a) else "ORDERED"):
            raise ValueError("contradictory_clock_order")
        if finish and finish["phase"] == "RAISED" and finish["return_code"] is not None:
            raise ValueError("invalid_raised_code")
        matches = None
        try:
            if state and state["service"] == "maintain":
                matches = e["supervisor_pid"] == state["supervisor_pid"] and a is not None and datetime.fromisoformat(a) >= datetime.fromisoformat(state["supervisor_started_at"])
        except (KeyError, ValueError, TypeError):
            matches = None
        interval = None
        if passes:
            previous = passes[-1]
            if previous["observer_id"] == e["observer_id"] and previous["supervisor_pid"] == e["supervisor_pid"] and previous["finished_at"] and a:
                delta = (datetime.fromisoformat(a)-datetime.fromisoformat(previous["finished_at"])).total_seconds()
                interval = delta if delta >= 0 and previous["wall_clock_order"] == "ORDERED" else None
        passes.append({"pass_id": pass_id, "observer_id": e["observer_id"], "supervisor_pid": e["supervisor_pid"],
                       "started_at": a, "finished_at": b, "phase": finish["phase"] if finish else "START",
                       "pair_state": "COMPLETE" if start and finish else "START_ONLY" if start else "END_ONLY",
                       "exit_code": finish["return_code"] if finish else None,
                       "duration_sec": finish["elapsed_sec"] if finish else None, "wall_clock_order": order,
                       "sleep_interval_sec": interval, "matches_current_state": matches})
    latest = max((datetime.fromisoformat(t) for r in passes for t in (r["started_at"], r["finished_at"]) if t), default=None)
    successes = [r for r in passes if r["pair_state"] == "COMPLETE" and r["phase"] == "FINISH" and r["exit_code"] == 0 and r["wall_clock_order"] == "ORDERED" and r["matches_current_state"] is True and r["finished_at"]]
    failures = sum(r["phase"] == "RAISED" or (r["exit_code"] is not None and r["exit_code"] != 0) for r in passes)
    return {"status": "OBSERVED", "as_of": as_of.isoformat(), "clock_owner": "HOST_UTC_SUPERVISOR",
            "experiment_evidence": False, "process_identity_verified": False, "downtime": "UNESTABLISHED",
            "scope": {"byte_limit": 1_000_000, "event_limit": 100, "pass_limit": 20, "retained_events": len(source["events"]),
                      "truncated": source.get("truncated", False) or len(passes) > 20, "duplicate_events": source.get("duplicate_events", 0)},
            "freshness": health.freshness(latest, as_of, 300), "last_successful_pass": successes[-1] if successes else None,
            "recent_failures": failures, "partial_passes": sum(r["pair_state"] != "COMPLETE" for r in passes),
            "large_observed_intervals": sum(r["sleep_interval_sec"] is not None and r["sleep_interval_sec"] > 30 for r in passes),
            "interval_warning_sec": 30, "passes": list(reversed(passes[-20:])), **AUTHORITY}


def read_local(as_of=None):
    source = read_observations(ROOT / "logs/v2-pass-provenance.jsonl", max_bytes=1_000_000, limit=100)
    try:
        with (ROOT / "logs/runtime-state-maintain.json").open("rb") as stream:
            state = json.loads(stream.read(16_384))
    except (OSError, ValueError):
        state = None
    return summarize_passes(source, state, as_of or datetime.now(timezone.utc))


async def operator_passes(session):
    try:
        result = await asyncio.wait_for(asyncio.to_thread(read_local), timeout=3)
    except Exception:
        return {"status": "UNAVAILABLE", "reason": "missing_or_invalid_pass_evidence", **AUTHORITY}
    if result["status"] != "OBSERVED":
        return result
    result["collection_freshness"] = {"status": "UNAVAILABLE", "age_sec": None, "latest_at": None, "scope": "LATEST_50_PLAN_MINTS", "as_of": None}
    try:
        async with asyncio.timeout(3):
            await session.execute(text("SET TRANSACTION READ ONLY"))
            await session.execute(text("SET LOCAL statement_timeout='1500ms'"))
            row = (await session.execute(text("""WITH selected AS (SELECT mint FROM intelligence_execution_v2_plans
                WHERE policy_version=:version ORDER BY id DESC LIMIT 50)
                SELECT clock_timestamp() AS as_of,max(s.captured_at) AS latest FROM (SELECT DISTINCT mint FROM selected) m
                CROSS JOIN LATERAL (SELECT captured_at FROM market_snapshots WHERE mint=m.mint AND captured_at<=clock_timestamp()
                    ORDER BY captured_at DESC LIMIT 1) s"""), {"version": POLICY_VERSION})).mappings().one()
            result["collection_freshness"] = {**health.freshness(row["latest"], row["as_of"], 300), "scope": "LATEST_50_PLAN_MINTS", "as_of": row["as_of"].isoformat()}
    except Exception:
        await session.rollback()
    return result


@router.get("/execution-v2/supervisor-passes")
async def endpoint(session=Depends(get_session)):
    return await operator_passes(session)
