"""Immutable prospective paper V2 admission and terminal evidence. No live execution."""
from __future__ import annotations
import argparse
import asyncio
import json
import math
from datetime import datetime, timedelta
import asyncpg
from freeze_intelligence_execution_v2 import ROOT, VERSION, policy, policy_hash, verify_registry

AUTHORITY = {"paper_only": True, "live_execution": False, "trading_authority": False,
             "transaction_signed": False, "order_submitted": False, "wallet_mutated": False,
             "performance_validation": False}

def decode(value):
    return json.loads(value) if isinstance(value, str) else value

def stamp(value):
    return value.isoformat()

def dt(value):
    return datetime.fromisoformat(value)

def positive(value):
    try:
        n = float(value)
        return n if math.isfinite(n) and n > 0 else None
    except (TypeError, ValueError):
        return None

def make_plan(source, boundary, now):
    p = policy()
    if source["policy_version"] != p["source_policy"] or source["decision"] != "PAPER_WOULD_ENTER":
        return None
    if not (boundary <= source["migration_at"] <= source["scored_at"] <= source["decided_at"] <= now):
        return None
    entry = source["decided_at"] + timedelta(seconds=p["entry_latency_sec"])
    if now >= entry:
        return None
    return {"policy_version": VERSION, "policy_sha256": policy_hash(p),
            "paper_decision_id": source["id"], "track_id": str(source["track_id"]), "mint": source["mint"],
            "prospective_boundary": stamp(boundary), "planned_at": stamp(now),
            "migration_at": stamp(source["migration_at"]), "scored_at": stamp(source["scored_at"]),
            "runtime_session": source.get("runtime_session"),
            "decided_at": stamp(source["decided_at"]), "entry_target": stamp(entry),
            "exit_target": stamp(entry + timedelta(seconds=p["hold_sec"])), **AUTHORITY}

def evaluate(plan, snapshots, as_of):
    p = policy()
    if plan["policy_version"] != VERSION or plan["policy_sha256"] != policy_hash(p):
        raise ValueError("policy_mismatch")
    entry_target, exit_target = dt(plan["entry_target"]), dt(plan["exit_target"])
    if not (dt(plan["prospective_boundary"]) <= dt(plan["migration_at"]) <= dt(plan["scored_at"])
            <= dt(plan["decided_at"]) <= dt(plan["planned_at"]) < entry_target):
        raise ValueError("contaminated_plan")
    if entry_target != dt(plan["decided_at"]) + timedelta(seconds=p["entry_latency_sec"]) or exit_target != entry_target + timedelta(seconds=p["hold_sec"]):
        raise ValueError("changed_schedule")
    maturity = exit_target + timedelta(seconds=p["observation_tolerance_sec"])
    base = {"policy_sha256": plan["policy_sha256"], "plan_sha256": policy_hash(plan),
            "as_of": stamp(as_of), "pricing": "snapshot_proxy_not_executable_fill", **AUTHORITY}
    if as_of < maturity:
        return {**base, "status": "PENDING", "window_complete": False}
    base["window_complete"] = True
    def observed(target):
        rows = [s for s in snapshots if s["mint"] == plan["mint"]
                and target <= s["captured_at"] <= target + timedelta(seconds=p["observation_tolerance_sec"])
                and s["captured_at"] <= as_of and positive(s["price_usd"]) is not None]
        return min(rows, key=lambda s: (s["captured_at"], str(s["snapshot_id"]))) if rows else None
    entry, exitrow = observed(entry_target), observed(exit_target)
    if entry is None:
        return {**base, "status": "UNKNOWN", "reason": "entry_observation_missing"}
    liquidity = positive(entry["liquidity_usd"])
    if liquidity is None:
        return {**base, "status": "UNKNOWN", "reason": "entry_liquidity_unknown"}
    if liquidity < p["min_entry_liquidity_usd"]:
        return {**base, "status": "REJECTED", "reason": "entry_liquidity_below_frozen_minimum"}
    if exitrow is None:
        return {**base, "status": "UNKNOWN", "reason": "exit_observation_missing"}
    gross = float(exitrow["price_usd"]) / float(entry["price_usd"])
    net = gross * (1-p["exit_fee_pct"]-p["exit_slippage_pct"]) / (1+p["entry_fee_pct"]+p["entry_slippage_pct"])
    def evidence(s):
        return {"snapshot_id": str(s["snapshot_id"]), "mint": s["mint"], "captured_at": stamp(s["captured_at"]),
                "price_usd": float(s["price_usd"]), "liquidity_usd": float(s["liquidity_usd"]) if positive(s["liquidity_usd"]) else None}
    return {**base, "status": "PAPER_PRICED", "entry": evidence(entry), "exit": evidence(exitrow),
            "entry_delay_sec": (entry["captured_at"]-entry_target).total_seconds(),
            "exit_delay_sec": (exitrow["captured_at"]-exit_target).total_seconds(),
            "gross_multiple": gross, "net_multiple": net, "paper_pnl_usd": p["paper_notional_usd"]*(net-1)}

async def run(conn, limit=500, runtime_session=None):
    registry = await conn.fetchrow("SELECT * FROM intelligence_execution_v2_registry WHERE policy_version=$1", VERSION)
    if not registry:
        raise ValueError("V2_not_frozen")
    verify_registry(registry)
    await conn.execute((ROOT / "services/post-migration-collector/migrations/008_intelligence_execution_v2_evidence.sql").read_text(encoding="utf-8"))
    sources = await conn.fetch("""SELECT d.id,d.track_id,d.mint,d.policy_version,d.decision,d.decided_at,
        s.scored_at,t.migration_at FROM intelligence_paper_decisions d
        JOIN intelligence_shadow_scores s ON s.id=d.shadow_score_id AND s.track_id=d.track_id AND s.mint=d.mint
        JOIN migration_tracks t ON t.track_id=d.track_id AND t.mint=d.mint
        WHERE d.policy_version=$1 AND d.decision='PAPER_WOULD_ENTER'
          AND t.migration_at >= $2 AND s.scored_at >= $2 AND d.decided_at >= $2
          AND d.decided_at + interval '30 seconds' > clock_timestamp()
          AND NOT EXISTS(SELECT 1 FROM intelligence_execution_v2_plans p WHERE p.paper_decision_id=d.id AND p.policy_version=$3)
        ORDER BY d.decided_at,d.id LIMIT $4""", policy()["source_policy"], registry["prospective_boundary"], VERSION, limit)
    admitted = 0
    for source in sources:
        source = {**dict(source), "runtime_session": runtime_session}
        plan = make_plan(source, registry["prospective_boundary"], await conn.fetchval("SELECT clock_timestamp()"))
        if plan is None:
            continue
        result = await conn.execute("""INSERT INTO intelligence_execution_v2_plans
            (policy_version,policy_sha256,paper_decision_id,track_id,mint,planned_at,entry_target,exit_target,plan,plan_sha256)
            SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10 WHERE clock_timestamp() < $7
            ON CONFLICT(policy_version,paper_decision_id) DO NOTHING""", VERSION, plan["policy_sha256"], source["id"],
            source["track_id"], source["mint"], dt(plan["planned_at"]), dt(plan["entry_target"]), dt(plan["exit_target"]),
            json.dumps(plan), policy_hash(plan))
        admitted += int(result.endswith("1"))
    as_of = await conn.fetchval("SELECT clock_timestamp()")
    plans = await conn.fetch("""SELECT p.id,p.plan,p.plan_sha256 FROM intelligence_execution_v2_plans p
        WHERE p.policy_version=$1 AND p.exit_target+interval '30 seconds' <= $2
        AND NOT EXISTS(SELECT 1 FROM intelligence_execution_v2_results r WHERE r.plan_id=p.id)
        ORDER BY p.id LIMIT $3""", VERSION, as_of, limit)
    recorded = 0
    for row in plans:
        plan = decode(row["plan"])
        if dt(plan["prospective_boundary"]) != registry["prospective_boundary"]:
            raise ValueError("boundary_mismatch")
        if policy_hash(plan) != row["plan_sha256"]:
            raise ValueError("plan_hash_mismatch")
        snapshots = await conn.fetch("""SELECT snapshot_id,mint,captured_at,price_usd,liquidity_usd
            FROM market_snapshots WHERE mint=$1 AND captured_at >= $2 AND captured_at <= $3
            ORDER BY captured_at,snapshot_id""", plan["mint"], dt(plan["entry_target"]),
            dt(plan["exit_target"])+timedelta(seconds=policy()["observation_tolerance_sec"]))
        result = evaluate(plan, snapshots, as_of)
        if result["status"] == "PENDING":
            continue
        status = await conn.execute("""INSERT INTO intelligence_execution_v2_results(plan_id,recorded_at,result,result_sha256)
            VALUES($1,$2,$3::jsonb,$4) ON CONFLICT(plan_id) DO NOTHING""", row["id"], as_of, json.dumps(result), policy_hash(result))
        recorded += int(status.endswith("1"))
    return {"admitted": admitted, "recorded": recorded, **AUTHORITY}

def observed_runtime_session():
    import os
    if os.name != "nt":
        return None
    from start_paper_runtime import _owned_supervisor, _windows_supervisor_identity
    try:
        state = json.loads((ROOT / "logs/runtime-state-collector.json").read_text(encoding="utf-8"))
        pid = int(state["supervisor_pid"])
        if not _owned_supervisor(pid, "collector", ROOT / "logs") or not _windows_supervisor_identity(pid, "collector"):
            return None
        return {"service": "collector", "supervisor_pid": pid, "started_at": state["supervisor_started_at"],
                "identity_verified": True}
    except (OSError, ValueError, KeyError):
        return None


def summarize(rows):
    from collections import Counter
    from statistics import mean, median
    counts = Counter()
    priced, mature_mints, sessions, priced_mints = [], set(), set(), set()
    for row in rows:
        plan = decode(row["plan"])
        if policy_hash(plan) != row["plan_sha256"] or plan["policy_sha256"] != policy_hash(policy()):
            raise ValueError("plan_integrity_failure")
        if row["result"] is None:
            counts["PENDING"] += 1
            continue
        result = decode(row["result"])
        if policy_hash(result) != row["result_sha256"] or result["plan_sha256"] != row["plan_sha256"]:
            raise ValueError("result_integrity_failure")
        if (result.get("status") not in {"UNKNOWN", "REJECTED", "PAPER_PRICED"}
                or result.get("window_complete") is not True
                or result.get("policy_sha256") != plan["policy_sha256"]
                or any(result.get(k) is not v or plan.get(k) is not v for k, v in AUTHORITY.items())
                or evaluate(plan, [], dt(result["as_of"]))["status"] == "PENDING"):
            raise ValueError("terminal_evidence_invalid")
        if result["status"] == "PAPER_PRICED":
            # Recompute from the bound snapshot evidence, never from later prices.
            snapshots = [{**result[k], "captured_at": dt(result[k]["captured_at"])} for k in ("entry", "exit")]
            if evaluate(plan, snapshots, dt(result["as_of"])) != result:
                raise ValueError("priced_evidence_invalid")
        counts[result["status"]] += 1
        mature_mints.add(plan["mint"])
        session = plan.get("runtime_session")
        if session and session.get("identity_verified") is True:
            sessions.add((session["service"], session["supervisor_pid"], session["started_at"]))
        if result["status"] == "PAPER_PRICED":
            priced.append(result)
            priced_mints.add(plan["mint"])
    mature = len(rows)-counts["PENDING"]
    unknown_fraction = counts["UNKNOWN"]/mature if mature else None
    gates = policy()["adequacy"]
    adequate = (len(mature_mints) >= gates["distinct_mint_mature_plans"]
                and len(sessions) >= gates["recorded_runtime_sessions"]
                and len(priced_mints) >= gates["complete_paths"]
                and unknown_fraction is not None and unknown_fraction <= gates["max_unknown_fraction"])
    return {"policy_version": VERSION, "policy_sha256": policy_hash(policy()), "counts": dict(counts),
            "distinct_mint_mature_plans": len(mature_mints), "verified_runtime_sessions": len(sessions),
            "unknown_fraction": unknown_fraction, "adequacy_status": "DESCRIPTIVE_REVIEW_ELIGIBLE" if adequate else "INSUFFICIENT_EVIDENCE",
            "evaluation_ready": adequate, "priced_paths": len(priced),
            "net_multiple_mean": mean(r["net_multiple"] for r in priced) if priced else None,
            "net_multiple_median": median(r["net_multiple"] for r in priced) if priced else None,
            "paper_pnl_usd": sum(r["paper_pnl_usd"] for r in priced) if priced else None,
            "entry_delay_sec_mean": mean(r["entry_delay_sec"] for r in priced) if priced else None,
            "exit_delay_sec_mean": mean(r["exit_delay_sec"] for r in priced) if priced else None,
            "cost_assumptions": {k:v for k,v in policy().items() if "fee_pct" in k or "slippage_pct" in k},
            "interpretation": "UNVALIDATED_PROSPECTIVE_PAPER_SNAPSHOT_PROXIES", **AUTHORITY}


async def report(conn):
    row = await conn.fetchrow("SELECT * FROM intelligence_execution_v2_registry WHERE policy_version=$1", VERSION)
    if not row: raise ValueError("V2_not_frozen")
    boundary = verify_registry(row)["prospective_boundary"]
    rows = await conn.fetch("""SELECT p.plan,p.plan_sha256,r.result,r.result_sha256
        FROM intelligence_execution_v2_plans p LEFT JOIN intelligence_execution_v2_results r ON r.plan_id=p.id
        WHERE p.policy_version=$1 ORDER BY p.id""", VERSION)
    return {**summarize(rows), "prospective_boundary": boundary, "read_only": True}


async def main():
    import os
    url = os.getenv("STINKY_DATABASE_URL", "postgresql://stinky:stinky@127.0.0.1:5433/stinky")
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://",1),timeout=10,command_timeout=30)
    try:
        result = await report(conn) if args.report else await run(conn, runtime_session=observed_runtime_session())
        print(json.dumps(result, sort_keys=True))
    finally: await conn.close()

if __name__ == "__main__": asyncio.run(main())
