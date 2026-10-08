"""Bounded read-only V2 collection checkpoint; never runs the paper worker.

Freshness thresholds are operator diagnostics, not experiment/adequacy policy.
Sparse admitted evidence and session starts cannot establish worker downtime.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

import asyncpg
import run_intelligence_execution_v2 as v2


def freshness(timestamp, as_of, stale_after_sec):
    if timestamp is None:
        return {"status": "UNAVAILABLE", "age_sec": None, "latest_at": None}
    age = (as_of - timestamp).total_seconds()
    return {"status": "CLOCK_INCONSISTENT" if age < 0 else "STALE" if age > stale_after_sec else "RECENT",
            "age_sec": age, "latest_at": timestamp.isoformat()}


def window_support(timestamps, target, as_of):
    """Current captured-time coverage, not ingestion history or reclassification."""
    times = sorted(set(t for t in timestamps if t <= as_of))
    end = target + timedelta(seconds=v2.policy()["observation_tolerance_sec"])
    before = max((t for t in times if t < target), default=None)
    after = min((t for t in times if t > end), default=None)
    return {"target": target.isoformat(), "window_end": end.isoformat(),
            "captured_in_window": sum(target <= t <= end for t in times),
            "preceding_capture": before.isoformat() if before else None,
            "following_capture": after.isoformat() if after else None,
            "bracketing_gap_sec": (after-before).total_seconds() if before and after else None,
            "following_delay_sec": (after-target).total_seconds() if after else None,
            "ingestion_delay": "UNAVAILABLE", "cause": "UNESTABLISHED"}


def missingness_change(rows, since):
    """Compare immutable terminal cohorts by recording time; never include pending."""
    cohorts = {"before": Counter(), "since": Counter()}
    for row in rows:
        if row["result"] is not None:
            result = v2.decode(row["result"])
            cohorts["since" if row["recorded_at"] >= since else "before"][result["status"]] += 1
    out = {}
    for name, counts in cohorts.items():
        n = sum(counts.values())
        out[name] = {"terminal_rows": n, "unknown_rows": counts["UNKNOWN"],
                     "unknown_fraction": counts["UNKNOWN"]/n if n else None}
    a, b = out["before"]["unknown_fraction"], out["since"]["unknown_fraction"]
    out["increasing"] = b > a if a is not None and b is not None else None
    out["interpretation"] = "DESCRIPTIVE_COHORT_COMPARISON_NOT_CAUSAL_OR_INDEPENDENT"
    return out


def runtime_health(state, identity_verified, as_of, stale_after_sec):
    if not state:
        return {"status": "UNAVAILABLE", "identity_verified": False}
    try:
        observed = datetime.fromisoformat(state["as_of"])
        if state["service"] not in {"collector", "maintain"} or observed.tzinfo is None:
            raise ValueError("invalid_state")
        age = freshness(observed, as_of, stale_after_sec)
        return {"status": "OWNED_SUPERVISOR_PRESENT" if identity_verified and age["status"] == "RECENT"
                else "UNVERIFIED_OR_STALE", "identity_verified": identity_verified,
                "heartbeat": age, "started_at": state.get("supervisor_started_at"),
                "application_health": "UNESTABLISHED"}
    except (KeyError, TypeError, ValueError):
        return {"status": "UNAVAILABLE", "identity_verified": False}


def local_runtime(root, as_of):
    from start_paper_runtime import _owned_supervisor, _windows_supervisor_identity
    out = {}
    for name in ("collector", "maintain"):
        try:
            state = json.loads((root / f"logs/runtime-state-{name}.json").read_text(encoding="utf-8"))
            pid = int(state["supervisor_pid"])
            owned = _owned_supervisor(pid, name, root / "logs", now=as_of) and _windows_supervisor_identity(pid, name)
        except (OSError, ValueError, KeyError, TypeError):
            state, owned = None, False
        out[name] = runtime_health(state, owned, as_of, 180)
    return out


def log_support(path, as_of, max_bytes=8_000_000):
    """Bounded log inventory; emit categories/times only, never raw secret text.

    Existing V2 success lines have no clock. File mtime is log activity only.
    Untimestamped errors cannot be assigned to a missing observation window.
    """
    try:
        stat = path.stat()
        offset = max(0, stat.st_size-max_bytes)
        with path.open("rb") as stream:
            stream.seek(offset)
            raw = stream.read(max_bytes)
        lines = raw.decode("utf-8", errors="replace").splitlines()
        if offset:
            lines = lines[1:]
    except OSError:
        return {"status": "UNAVAILABLE", "timestamped_events": [], "v2_success_lines": None}
    events, counts, successes, clocks = [], Counter(), 0, []
    patterns = {"connection_reset": r"WinError 64|ConnectionResetError",
                "consumer_group_missing": r"NOGROUP", "provider_rate_limit": r"\b429 (?:Too Many|Client Error)|status(?:_code)?[=:]429\b|rate.limit",
                "v2_capture_error": r"intelligence V2 capture error",
                "supervisor_exit": r"\] exit=", "supervisor_start": r"\] start pid="}
    for line in lines:
        match = re.match(r"\[?(\d{4}-\d{2}-\d{2}T[0-9:.]+(?:Z|[+-][0-9:]+))", line)
        clock = None
        if match:
            try:
                clock = datetime.fromisoformat(match.group(1))
                clocks.append(clock)
            except ValueError:
                pass
        try:
            payload = json.loads(line)
            if (isinstance(payload, dict) and all(type(payload.get(k)) is int and payload[k] >= 0 for k in ("admitted", "recorded"))
                    and all(payload.get(k) is v for k, v in v2.AUTHORITY.items())):
                successes += 1
        except (ValueError, TypeError):
            pass
        for label, pattern in patterns.items():
            if re.search(pattern, line):
                counts[label] += 1
                if clock:
                    events.append({"category": label, "at": clock.isoformat()})
    return {"status": "OBSERVED", "tail_truncated": bool(offset), "bytes_read": len(raw),
            "log_activity": freshness(datetime.fromtimestamp(stat.st_mtime, timezone.utc), as_of, 300),
            "category_line_counts": dict(counts), "timestamped_events": events,
            "earliest_timestamp": min(clocks).isoformat() if clocks else None,
            "latest_timestamp": max(clocks).isoformat() if clocks else None,
            "v2_success_lines": successes, "v2_success_timestamps": "UNAVAILABLE",
            "interpretation": "PARTIAL_LOG_SUPPORT_NOT_CONTINUOUS_COVERAGE_OR_CAUSATION"}


def correlate_logs(missing, logs):
    for row in missing:
        support = row["current_capture_support"]
        start, end = v2.dt(support["target"]), v2.dt(support["window_end"])
        row["coincident_log_events"] = [e for log in logs.values() for e in log["timestamped_events"]
                                        if start <= v2.dt(e["at"]) <= end]
        row["log_cause"] = "UNESTABLISHED"


async def collect(conn, *, stale_after_sec=300, compare_since=None):
    async with conn.transaction(isolation="repeatable_read", readonly=True):
        as_of = await conn.fetchval("SELECT clock_timestamp()")
        reg = await conn.fetchrow("SELECT * FROM intelligence_execution_v2_registry WHERE policy_version=$1", v2.VERSION)
        registry = v2.verify_registry(reg) if reg else None
        if registry is None:
            raise ValueError("registry_unavailable")
        rows = await conn.fetch("""SELECT p.id,p.plan,p.plan_sha256,r.result,r.result_sha256,r.recorded_at
            FROM intelligence_execution_v2_plans p LEFT JOIN intelligence_execution_v2_results r ON r.plan_id=p.id
            WHERE p.policy_version=$1 ORDER BY p.id""", v2.VERSION)
        canonical = v2.summarize(rows)
        reasons, authority = Counter(), Counter({k: 0 for k in v2.AUTHORITY if k not in {"paper_only", "performance_validation"}})
        sessions, missing, overdue = {}, [], []
        for row in rows:
            plan = v2.decode(row["plan"])
            result = v2.decode(row["result"]) if row["result"] is not None else None
            if v2.dt(plan["prospective_boundary"]) != reg["prospective_boundary"]:
                raise ValueError("boundary_mismatch")
            for payload in (plan, result):
                if payload is not None:
                    for key in authority:
                        authority[key] += int(payload.get(key) is not False)
            maturity = v2.dt(plan["exit_target"])+timedelta(seconds=v2.policy()["observation_tolerance_sec"])
            if result is None and as_of >= maturity:
                overdue.append({"plan_id": row["id"], "overdue_sec": (as_of-maturity).total_seconds()})
            session = plan.get("runtime_session")
            if result and session and session.get("identity_verified") is True:
                key = (session["service"], session["supervisor_pid"], session["started_at"])
                sessions[key] = {"service": key[0], "supervisor_pid": key[1], "started_at": key[2]}
            if result and result.get("reason"):
                reasons[(result["status"], result["reason"])] += 1
            if result and result.get("reason") in {"entry_observation_missing", "exit_observation_missing"}:
                phase = "entry" if result["reason"] == "entry_observation_missing" else "exit"
                target = v2.dt(plan[f"{phase}_target"])
                samples = await conn.fetch("""SELECT captured_at FROM market_snapshots
                    WHERE mint=$1 AND captured_at BETWEEN $2 AND $3 AND captured_at <= $4
                    ORDER BY captured_at""", plan["mint"], target-timedelta(seconds=120), target+timedelta(seconds=150), as_of)
                missing.append({"plan_id": row["id"], "status": result["status"], "recorded_reason": result["reason"],
                                "current_capture_support": window_support([s["captured_at"] for s in samples], target, as_of)})
        latest_snapshot = await conn.fetchval("SELECT max(captured_at) FROM market_snapshots WHERE captured_at <= $1", as_of)
        guards = await conn.fetchval("""SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgname IN
            ('execution_v2_plans_immutable','execution_v2_plans_no_truncate','execution_v2_results_immutable',
             'execution_v2_results_no_truncate','execution_v2_registry_immutable','execution_v2_registry_no_truncate')""")
        if any(authority.values()) or guards != 6:
            raise ValueError("safety_integrity_failure")
        latest_result = max((r["recorded_at"] for r in rows if r["result"] is not None), default=None)
        return {"status": "OBSERVED", "as_of": as_of.isoformat(), "read_only": True, "paper_only": True,
                "registry": registry, "registry_rows": await conn.fetchval("SELECT count(*) FROM intelligence_execution_v2_registry"),
                "canonical": {k: canonical[k] for k in ("counts", "distinct_mint_mature_plans", "verified_runtime_sessions",
                    "priced_paths", "unknown_fraction", "adequacy_status", "evaluation_ready")},
                "freshness_threshold_sec": stale_after_sec,
                "latest_market_capture": freshness(latest_snapshot, as_of, stale_after_sec),
                "latest_terminal_recording": freshness(latest_result, as_of, stale_after_sec),
                "mature_without_result": overdue, "verified_admitted_sessions": list(sessions.values()),
                "session_end_times": "UNAVAILABLE", "worker_downtime": "UNESTABLISHED",
                "recorded_reasons": [{"status": s, "reason": r, "count": n} for (s, r), n in sorted(reasons.items())],
                "missing_window_support": missing, "authority_violations": dict(authority), "immutable_guards": guards,
                "missingness_change": missingness_change(rows, compare_since) if compare_since else None}


async def checkpoint(connect, **kwargs):
    """A disconnected/invalid checkpoint has no invented metrics or exception secrets."""
    conn = None
    try:
        conn = await connect()
        return await collect(conn, **kwargs)
    except (asyncpg.PostgresError, OSError, TimeoutError, ValueError, KeyError, TypeError):
        return {"status": "UNAVAILABLE", "read_only": True, "paper_only": True,
                "reason": "connection_or_evidence_validation_failed", "canonical": None}
    finally:
        if conn is not None:
            await conn.close()


async def main():
    from stinky_api.config import settings
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stale-after-sec", type=float, default=300)
    parser.add_argument("--compare-since", type=datetime.fromisoformat)
    args = parser.parse_args()
    if not 0 < args.stale_after_sec < float("inf") or (args.compare_since and args.compare_since.tzinfo is None):
        parser.error("positive finite freshness threshold and timezone-aware comparison required")
    async def connect():
        return await asyncpg.connect(settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1),
                                     timeout=10, command_timeout=30)
    result = await checkpoint(connect, stale_after_sec=args.stale_after_sec, compare_since=args.compare_since)
    result["runtime"] = local_runtime(v2.ROOT, datetime.now(timezone.utc))
    result["logs"] = {name: log_support(v2.ROOT / f"logs/{name}.log", datetime.now(timezone.utc))
                      for name in ("collector", "maintain")}
    correlate_logs(result.get("missing_window_support", []), result["logs"])
    result["limitations"] = ["Capture timestamps do not establish ingestion delay or upstream causation.",
        "Session starts are not continuous coverage or end/downtime boundaries.",
        "No recent admission/result can mean no eligible candidates, not worker failure.",
        "Freshness threshold is diagnostic only; no frozen timing or adequacy change."]
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "OBSERVED" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
