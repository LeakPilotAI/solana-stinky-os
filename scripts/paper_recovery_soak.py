"""Bounded paper-worker stability soak certification.

This is an operational durability check, not trading-performance validation.
It never grants live authority and does not contact Solana RPC.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paper_recovery_drill import (
    AUTHORITY, DIAGNOSTICS, LOGS, WORKERS, _duplicates, _duplicates_zero,
    _file_stamp, _owned_detail, _pg, _preserved_subset, _run_schema_gate,
    _snapshot, _snapshot_summary, _start_workers, _utc_stamp, _write_report,
)
from start_paper_runtime import _owned_supervisor

DEFAULT_DURATION_SECONDS = 300
DEFAULT_SAMPLE_SECONDS = 30


def _sample_identity(name: str, expected: dict[str, Any]) -> dict[str, Any]:
    pid = int(expected["pid"])
    current = _owned_detail(name, pid)
    if current.get("supervisor_started_at") != expected.get("supervisor_started_at"):
        raise RuntimeError(f"supervisor_identity_changed:{name}")
    if str(current.get("phase") or "").upper() == "FAILED":
        raise RuntimeError(f"supervisor_failed:{name}")
    return current


def _iso(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise RuntimeError("naive_heartbeat_timestamp")
    return parsed.astimezone(timezone.utc)


def certify(duration_seconds: int, sample_seconds: int) -> dict[str, Any]:
    if duration_seconds < 120:
        raise RuntimeError("soak_duration_too_short")
    if sample_seconds < 5 or sample_seconds > 60:
        raise RuntimeError("invalid_sample_interval")

    _run_schema_gate()
    pg = _pg()
    initial_supervisors = _start_workers()
    before = _snapshot(pg)
    dup_before = _duplicates(pg)
    if not _duplicates_zero(dup_before):
        raise RuntimeError("preexisting_duplicate_paper_evidence")

    samples: list[dict[str, Any]] = []
    first_heartbeat = {name: _iso(initial_supervisors[name]["as_of"]) for name in WORKERS}
    deadline = time.monotonic() + duration_seconds
    while True:
        observed = {name: _sample_identity(name, initial_supervisors[name]) for name in WORKERS}
        samples.append({"observed_at": _utc_stamp(), "supervisors": observed})
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(float(sample_seconds), remaining))

    final_supervisors = {name: _sample_identity(name, initial_supervisors[name]) for name in WORKERS}
    after = _snapshot(pg)
    dup_after = _duplicates(pg)

    candidate_ok, candidate_changed = _preserved_subset(
        before.get("candidates"), after.get("candidates"), key="candidate_id"
    )
    intake_ok, intake_changed = _preserved_subset(
        before.get("intakes"), after.get("intakes"), key="intake_id"
    )
    runtime_ok, runtime_changed = _preserved_subset(
        before.get("runtime_records"), after.get("runtime_records"), key="intake_id"
    )
    heartbeat_advanced = {
        name: _iso(final_supervisors[name]["as_of"]) > first_heartbeat[name] for name in WORKERS
    }
    checks = {
        "supervisor_identity_stable": all(
            int(final_supervisors[n]["pid"]) == int(initial_supervisors[n]["pid"])
            and final_supervisors[n].get("supervisor_started_at") == initial_supervisors[n].get("supervisor_started_at")
            for n in WORKERS
        ),
        "heartbeats_advanced": all(heartbeat_advanced.values()),
        "candidate_t0_identity_preserved": candidate_ok,
        "intake_payload_identity_preserved": intake_ok,
        "existing_runtime_records_preserved": runtime_ok,
        "producer_epoch_unchanged": before.get("producer") == after.get("producer"),
        "active_policy_provenance_unchanged": before.get("active_policy") == after.get("active_policy"),
        "duplicates_before_zero": _duplicates_zero(dup_before),
        "duplicates_after_zero": _duplicates_zero(dup_after),
        "all_supervisors_owned_at_completion": all(
            _owned_supervisor(int(final_supervisors[n]["pid"]), n, LOGS) for n in WORKERS
        ),
    }
    if not all(checks.values()):
        raise RuntimeError("bounded_soak_invariant_failed")

    active_policy_count = len(before.get("active_policy") or [])
    return {
        "status": "PASS",
        "certification_scope": "idle_runtime_recovery_stability" if active_policy_count == 0 else "runtime_recovery_stability",
        "performance_validation": False,
        "duration_seconds": duration_seconds,
        "sample_seconds": sample_seconds,
        "sample_count": len(samples),
        "initial_supervisors": initial_supervisors,
        "final_supervisors": final_supervisors,
        "heartbeat_advanced": heartbeat_advanced,
        "before": _snapshot_summary(before),
        "after": _snapshot_summary(after),
        "duplicates_before": dup_before,
        "duplicates_after": dup_after,
        "checks": checks,
        "changed_preexisting_ids": {
            "candidates": candidate_changed,
            "intakes": intake_changed,
            "runtime_records": runtime_changed,
        },
        "active_policy_count": active_policy_count,
        "samples": samples,
        **AUTHORITY,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=int, default=DEFAULT_DURATION_SECONDS)
    parser.add_argument("--sample-seconds", type=int, default=DEFAULT_SAMPLE_SECONDS)
    args = parser.parse_args()
    DIAGNOSTICS.mkdir(parents=True, exist_ok=True)
    report_path = DIAGNOSTICS / f"paper-recovery-soak-{_file_stamp()}.json"
    report: dict[str, Any] = {
        "status": "FAIL", "started_at": _utc_stamp(), "report_file": str(report_path), **AUTHORITY
    }
    try:
        if os.name != "nt":
            raise RuntimeError("paper_recovery_soak_requires_windows")
        result = certify(args.duration_seconds, args.sample_seconds)
        report.update(result)
        report["certified_at"] = _utc_stamp()
        _write_report(report, report_path)
        print(json.dumps(report, sort_keys=True, default=str), flush=True)
        print("[soak] BOUNDED PAPER RECOVERY SOAK PASSED", flush=True)
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError) as exc:
        report["error"] = f"{type(exc).__name__}:{exc}"
        report["failed_at"] = _utc_stamp()
        _write_report(report, report_path)
        print(json.dumps(report, sort_keys=True, default=str), flush=True)
        print("[soak] BOUNDED PAPER RECOVERY SOAK FAILED", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
