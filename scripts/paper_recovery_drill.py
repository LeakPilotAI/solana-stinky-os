"""Controlled paper-worker kill/restart recovery certification.

Windows-local operational drill. It proves Genesis supervisor ownership before
terminating anything, preserves durable paper evidence identities, and never
contacts RPC, signs, submits, mutates wallets, or grants live authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.genesis_postgres_backup import BackupError, PgTools  # noqa: E402
from scripts.start_paper_runtime import (  # noqa: E402
    WORKERS,
    _alive,
    _known_pids,
    _legacy_supervisor_instance_identity,
    _owned_supervisor,
    _windows_supervisor_identity,
    _write_pids,
)

LOGS = ROOT / "logs"
PID_FILE = LOGS / "stinky-pids.txt"
DIAGNOSTICS = LOGS / "diagnostics"

AUTHORITY = {
    "paper_only": True,
    "live_execution": False,
    "trading_authority": False,
    "rpc_contacted": False,
    "transaction_signed": False,
    "order_submitted": False,
    "wallet_mutated": False,
}


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _file_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _canonical_digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _run(cmd: list[str], *, timeout: int = 120, capture: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if capture and result.stdout:
        print(result.stdout.rstrip(), flush=True)
    if capture and result.stderr:
        print(result.stderr.rstrip(), flush=True)
    return result


def _run_schema_gate() -> None:
    print("[recovery] applying/verifying strict startup schema gate...", flush=True)
    result = _run([sys.executable, str(ROOT / "scripts" / "strict_startup_schema_gate.py")], timeout=240)
    if result.returncode != 0:
        raise RuntimeError("strict_schema_gate_failed")
    print("[recovery] strict schema gate PASS", flush=True)


def _state(name: str) -> dict[str, Any]:
    path = LOGS / f"runtime-state-{name}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _state_pid(name: str) -> int:
    value = _state(name).get("supervisor_pid")
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _owned_detail(name: str, pid: int) -> dict[str, Any]:
    if not _owned_supervisor(pid, name, LOGS):
        raise RuntimeError(f"supervisor_ownership_not_proven:{name}:{pid}")
    state = _state(name)
    return {
        "service": name,
        "pid": pid,
        "supervisor_started_at": state.get("supervisor_started_at"),
        "as_of": state.get("as_of"),
        "phase": state.get("supervisor_phase"),
    }


def _cleanup_proven_orphan(name: str, pid: int) -> None:
    """Remove only a live PID whose Windows command line proves exact Genesis ownership."""
    if not _alive(pid):
        return
    command_identity = _windows_supervisor_identity(pid, name)
    legacy_instance_identity = _legacy_supervisor_instance_identity(pid, name, LOGS)
    if not (command_identity or legacy_instance_identity):
        raise RuntimeError(f"live_unowned_supervisor_identity_not_proven:{name}:{pid}")
    print(
        f"[recovery] cleaning proven orphaned Genesis supervisor {name} pid={pid}...",
        flush=True,
    )
    if os.name != "nt":
        raise RuntimeError("orphan_cleanup_requires_windows")
    result = subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    )
    if result.returncode != 0 and _alive(pid):
        raise RuntimeError(
            f"proven_orphan_cleanup_failed:{name}:{pid}:"
            f"{(result.stderr or result.stdout or '')[-300:]}"
        )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not _alive(pid):
            return
        time.sleep(0.25)
    raise RuntimeError(f"proven_orphan_still_alive:{name}:{pid}")


def _reconcile_pid_file() -> dict[str, int]:
    known = _known_pids(PID_FILE)
    changed = False
    for name in WORKERS:
        file_pid = int(known.get(name, 0) or 0)
        state_pid = _state_pid(name)

        # A fresh durable heartbeat is the normal ownership proof. A live PID
        # with stale state can be a supervisor orphaned by a prior failed
        # startup cleanup; never kill it from stale state alone. First prove
        # the exact Windows command line belongs to this Genesis worker.
        candidates = []
        for pid in (file_pid, state_pid):
            if pid > 0 and pid not in candidates:
                candidates.append(pid)
        for pid in candidates:
            if not _alive(pid):
                continue
            if _owned_supervisor(pid, name, LOGS):
                if file_pid != pid:
                    known[name] = pid
                    file_pid = pid
                    changed = True
                continue
            _cleanup_proven_orphan(name, pid)
            if int(known.get(name, 0) or 0) == pid:
                known.pop(name, None)
                file_pid = 0
                changed = True
            state_path = LOGS / f"runtime-state-{name}.json"
            if _state_pid(name) == pid:
                try:
                    state_path.unlink()
                except FileNotFoundError:
                    pass

        file_pid = int(known.get(name, 0) or 0)
        if file_pid > 0 and not _alive(file_pid):
            known.pop(name, None)
            changed = True

    if changed:
        _write_pids(PID_FILE, known)
    return known


def _start_workers() -> dict[str, dict[str, Any]]:
    known = _reconcile_pid_file()
    missing = [name for name in WORKERS if not _owned_supervisor(int(known.get(name, 0) or 0), name, LOGS)]
    if missing:
        print("[recovery] starting/proving paper supervisors: " + ", ".join(missing), flush=True)
        result = _run([sys.executable, str(ROOT / "scripts" / "start_paper_runtime.py")], timeout=60)
        if result.returncode != 0:
            raise RuntimeError("paper_supervisor_start_failed")
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        known = _reconcile_pid_file()
        if all(_owned_supervisor(int(known.get(name, 0) or 0), name, LOGS) for name in WORKERS):
            return {
                name: _owned_detail(name, int(known[name]))
                for name in WORKERS
            }
        time.sleep(0.5)
    raise RuntimeError("paper_supervisor_ownership_timeout")


def _kill_owned_supervisor(name: str, pid: int) -> None:
    _owned_detail(name, pid)  # fail closed immediately before termination
    print(f"[recovery] terminating verified Genesis supervisor tree {name} pid={pid}...", flush=True)
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        if result.returncode != 0 and _alive(pid):
            raise RuntimeError(f"owned_supervisor_kill_failed:{name}:{pid}:{(result.stderr or result.stdout or '')[-300:]}")
    else:
        os.kill(pid, signal.SIGTERM)

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not _alive(pid):
            return
        time.sleep(0.25)
    raise RuntimeError(f"owned_supervisor_still_alive:{name}:{pid}")


SNAPSHOT_SQL = r"""
SELECT jsonb_build_object(
  'producer',
  COALESCE((
    SELECT jsonb_agg(
      jsonb_build_object(
        'producer_version', s.producer_version,
        'prospective_started_at', s.prospective_started_at
      )
      ORDER BY s.producer_version, s.prospective_started_at
    )
    FROM paper_intake_producer_state s
  ), '[]'::jsonb),

  'candidates',
  COALESCE((
    SELECT jsonb_agg(
      jsonb_build_object(
        'candidate_id', c.candidate_id,
        'source_event_id', c.source_event_id,
        'mint', c.mint,
        'decided_at', c.decided_at,
        'source_event_occurred_at', c.source_event_occurred_at,
        'source_event_ingested_at', c.source_event_ingested_at,
        'producer_version', c.producer_version,
        'filter_version', c.filter_version,
        'cohort_pattern_hash', c.cohort_pattern_hash,
        't0_evidence_sha256', c.t0_evidence_sha256,
        'frozen_bundle_sha256', c.frozen_bundle_sha256,
        'reference_entry_price', c.reference_entry_price,
        'close_due_at', c.close_due_at,
        'open_intake_id', c.open_intake_id
      )
      ORDER BY c.candidate_id
    )
    FROM paper_prospective_candidate c
  ), '[]'::jsonb),

  'intakes',
  COALESCE((
    SELECT jsonb_agg(
      jsonb_build_object(
        'intake_id', i.intake_id,
        'mint', i.mint,
        'observed_at', i.observed_at,
        'payload_sha256', i.payload_sha256
      )
      ORDER BY i.intake_id
    )
    FROM paper_runtime_intake i
  ), '[]'::jsonb),

  'runtime_records',
  COALESCE((
    SELECT jsonb_agg(
      jsonb_build_object(
        'intake_id', r.intake_id,
        'mint', r.mint,
        'decided_at', r.decided_at,
        'shadow_status', r.shadow_status,
        'shadow_action', r.shadow_action,
        'paper_status', r.paper_status,
        'policy_version', r.policy_version,
        'policy_sha256', r.policy_sha256,
        'policy_evidence_backed', r.policy_evidence_backed,
        'record', r.record
      )
      ORDER BY r.intake_id
    )
    FROM paper_runtime_record r
  ), '[]'::jsonb),

  'active_policy',
  COALESCE((
    SELECT jsonb_agg(
      jsonb_build_object(
        'policy_version', a.policy_version,
        'activated_at', a.activated_at,
        'policy_sha256', p.policy_sha256,
        'policy_payload', p.policy_payload
      )
      ORDER BY a.policy_version
    )
    FROM paper_policy_active a
    JOIN paper_policy_registry p ON p.policy_version=a.policy_version
  ), '[]'::jsonb)
)::text;
"""

DUPLICATES_SQL = r"""
SELECT jsonb_build_object(
  'candidate_id', (
    SELECT count(*) FROM (
      SELECT candidate_id FROM paper_prospective_candidate
      GROUP BY candidate_id HAVING count(*) > 1
    ) q
  ),
  'candidate_source_event_id', (
    SELECT count(*) FROM (
      SELECT source_event_id FROM paper_prospective_candidate
      GROUP BY source_event_id HAVING count(*) > 1
    ) q
  ),
  'candidate_open_intake_id', (
    SELECT count(*) FROM (
      SELECT open_intake_id FROM paper_prospective_candidate
      WHERE open_intake_id IS NOT NULL
      GROUP BY open_intake_id HAVING count(*) > 1
    ) q
  ),
  'candidate_close_intake_id', (
    SELECT count(*) FROM (
      SELECT close_intake_id FROM paper_prospective_candidate
      WHERE close_intake_id IS NOT NULL
      GROUP BY close_intake_id HAVING count(*) > 1
    ) q
  ),
  'runtime_intake_id', (
    SELECT count(*) FROM (
      SELECT intake_id FROM paper_runtime_intake
      GROUP BY intake_id HAVING count(*) > 1
    ) q
  ),
  'runtime_record_intake_id', (
    SELECT count(*) FROM (
      SELECT intake_id FROM paper_runtime_record
      GROUP BY intake_id HAVING count(*) > 1
    ) q
  )
)::text;
"""


def _pg() -> PgTools:
    return PgTools(
        mode="docker-network",
        user="stinky",
        container="stinky-postgres",
        network="project-genesis_default",
        db_host="postgres",
        port=5432,
        password="stinky",
        discover_container_endpoint=True,
    )


def _snapshot(pg: PgTools) -> dict[str, Any]:
    raw = pg.psql("stinky", SNAPSHOT_SQL)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError("invalid_recovery_snapshot")
    return value


def _duplicates(pg: PgTools) -> dict[str, int]:
    raw = pg.psql("stinky", DUPLICATES_SQL)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError("invalid_duplicate_snapshot")
    return {str(k): int(v or 0) for k, v in value.items()}


def _row_map(rows: Any, key: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        ident = str(row.get(key) or "")
        if ident:
            out[ident] = row
    return out


def _preserved_subset(
    before_rows: Any,
    after_rows: Any,
    *,
    key: str,
) -> tuple[bool, list[str]]:
    before = _row_map(before_rows, key)
    after = _row_map(after_rows, key)
    changed = [
        ident
        for ident, row in before.items()
        if ident not in after or after[ident] != row
    ]
    return not changed, changed


def _duplicates_zero(value: dict[str, int]) -> bool:
    return all(int(v) == 0 for v in value.values())


def _snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "digest": _canonical_digest(snapshot),
        "counts": {
            key: len(snapshot.get(key) or [])
            for key in ("producer", "candidates", "intakes", "runtime_records", "active_policy")
        },
    }


def _write_report(report: dict[str, Any], path: Path) -> None:
    DIAGNOSTICS.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    DIAGNOSTICS.mkdir(parents=True, exist_ok=True)
    report_path = DIAGNOSTICS / f"paper-recovery-drill-{_file_stamp()}.json"
    report: dict[str, Any] = {
        "status": "FAIL",
        "started_at": _utc_stamp(),
        "report_file": str(report_path),
        **AUTHORITY,
    }
    ownership_proven = False

    try:
        if os.name != "nt":
            raise RuntimeError("paper_recovery_drill_requires_windows")

        _run_schema_gate()
        pg = _pg()

        initial_supervisors = _start_workers()
        ownership_proven = True
        print("[recovery] both paper supervisors are Genesis-owned", flush=True)

        before = _snapshot(pg)
        dup_before = _duplicates(pg)
        if not _duplicates_zero(dup_before):
            raise RuntimeError("preexisting_duplicate_paper_evidence")

        report["before"] = _snapshot_summary(before)
        report["duplicates_before"] = dup_before
        report["initial_supervisors"] = initial_supervisors

        recoveries: list[dict[str, Any]] = []
        for name in WORKERS:
            known = _reconcile_pid_file()
            old_pid = int(known.get(name, 0) or 0)
            old = _owned_detail(name, old_pid)
            _kill_owned_supervisor(name, old_pid)

            recovered = _start_workers()
            new = recovered[name]
            if new.get("supervisor_started_at") == old.get("supervisor_started_at"):
                raise RuntimeError(f"supervisor_restart_not_proven:{name}")
            recoveries.append({"service": name, "before": old, "after": new})
            print(
                f"[recovery] {name} recovered: pid {old_pid} -> {new.get('pid')}",
                flush=True,
            )

        time.sleep(5.0)

        final_supervisors = _start_workers()
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

        checks = {
            "candidate_t0_identity_preserved": candidate_ok,
            "intake_payload_identity_preserved": intake_ok,
            "existing_runtime_records_preserved": runtime_ok,
            "producer_epoch_unchanged": before.get("producer") == after.get("producer"),
            "active_policy_provenance_unchanged": before.get("active_policy") == after.get("active_policy"),
            "duplicates_before_zero": _duplicates_zero(dup_before),
            "duplicates_after_zero": _duplicates_zero(dup_after),
            "all_supervisors_recovered": all(
                _owned_supervisor(int(final_supervisors[name]["pid"]), name, LOGS)
                for name in WORKERS
            ),
            "both_supervisors_forced_and_restarted": len(recoveries) == len(WORKERS),
        }

        report.update(
            {
                "after": _snapshot_summary(after),
                "duplicates_after": dup_after,
                "recoveries": recoveries,
                "final_supervisors": final_supervisors,
                "checks": checks,
                "changed_preexisting_ids": {
                    "candidates": candidate_changed,
                    "intakes": intake_changed,
                    "runtime_records": runtime_changed,
                },
            }
        )

        if not all(checks.values()):
            raise RuntimeError("recovery_invariant_failed")

        report["status"] = "PASS"
        report["certified_at"] = _utc_stamp()
        _write_report(report, report_path)
        print(json.dumps(report, sort_keys=True, default=str), flush=True)
        print("[recovery] PAPER WORKER RECOVERY DRILL PASSED", flush=True)
        return 0

    except (BackupError, RuntimeError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        report["error"] = f"{type(exc).__name__}:{exc}"
        report["failed_at"] = _utc_stamp()
        print(json.dumps(report, sort_keys=True, default=str), flush=True)
        print("[recovery] PAPER WORKER RECOVERY DRILL FAILED", flush=True)
        return 1
    finally:
        if ownership_proven:
            try:
                _start_workers()
            except Exception as exc:
                report["recovery_cleanup_error"] = f"{type(exc).__name__}:{exc}"
        try:
            _write_report(report, report_path)
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
