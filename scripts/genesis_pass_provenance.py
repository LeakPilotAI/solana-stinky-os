"""Forward-only supervisor observations, separate from immutable experiment evidence."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import threading
import time
from uuid import UUID, uuid4

MAX_BYTES = 1_000_000
FIELDS = {"schema", "observer_id", "event_id", "pass_id", "supervisor_pid", "activity", "phase",
          "observed_at", "clock_owner", "elapsed_sec", "wall_clock_order", "return_code", "experiment_evidence"}


def timestamp(clock):
    try:
        value = clock()
        return value.astimezone(timezone.utc).isoformat() if isinstance(value, datetime) and value.tzinfo else None
    except Exception:
        return None


class Recorder:
    def __init__(self, path: Path, max_bytes=MAX_BYTES):
        self.path, self.max_bytes = path, max_bytes
        self.observer_id = str(uuid4())  # Local observer instance, NEVER a V2 observation session.
        self.lock = threading.Lock()

    def emit(self, record):
        try:
            if set(record) != FIELDS:
                return False
            encoded = (json.dumps(record, sort_keys=True, allow_nan=False)+"\n").encode("utf-8")
            if len(encoded) > self.max_bytes:
                return False
            with self.lock:
                if self.path.is_symlink() or self.path.with_suffix(".previous.jsonl").is_symlink():
                    return False
                if self.path.exists() and self.path.stat().st_size+len(encoded) > self.max_bytes:
                    self.path.replace(self.path.with_suffix(".previous.jsonl"))
                with self.path.open("ab") as stream:
                    stream.write(encoded)
            return True
        except (OSError, TypeError, ValueError):
            return False  # Diagnostic sink failure must not change worker behavior.


def observe_pass(job, recorder, *, clock=lambda: datetime.now(timezone.utc), monotonic=time.monotonic):
    pass_id = str(uuid4())
    started = timestamp(clock)
    try:
        start_tick = monotonic()
    except Exception:
        start_tick = None

    def emit(phase, observed_at, elapsed=None, order="UNAVAILABLE", code=None):
        record = {"schema": "genesis-supervisor-pass-v1", "observer_id": recorder.observer_id,
                  "event_id": f"{pass_id}:{phase}", "pass_id": pass_id, "supervisor_pid": os.getpid(),
                  "activity": "intelligence-execution-v2", "phase": phase, "observed_at": observed_at,
                  "clock_owner": "HOST_UTC_SUPERVISOR", "elapsed_sec": elapsed, "wall_clock_order": order,
                  "return_code": code, "experiment_evidence": False}
        try:
            recorder.emit(record)
        except Exception:
            pass  # A disconnected diagnostic sink never retries or suppresses a job.

    emit("START", started)
    code, phase = None, "RAISED"
    try:
        code = job()
        phase = "FINISH"
        return code
    finally:
        finished = timestamp(clock)
        try:
            elapsed = monotonic()-start_tick if start_tick is not None else None
            if elapsed is not None and (not math.isfinite(elapsed) or elapsed < 0):
                elapsed = None
        except Exception:
            elapsed = None
        order = ("REGRESSION" if finished < started else "ORDERED") if started and finished else "UNAVAILABLE"
        emit(phase, finished, elapsed, order, code if type(code) is int else None)


def read_observations(path: Path, max_bytes=MAX_BYTES, limit=100):
    """Read a bounded tail; incomplete/invalid/duplicate events cannot imply coverage."""
    try:
        size = path.stat().st_size
        offset = max(0, size-max_bytes)
        with path.open("rb") as stream:
            stream.seek(offset)
            raw = stream.read(max_bytes)
        lines = raw.decode("utf-8", errors="replace").splitlines()
        if offset:
            lines = lines[1:]
    except OSError:
        return {"status": "UNAVAILABLE", "events": [], "downtime": "UNESTABLISHED"}
    events, seen, conflicts, invalid, duplicates = [], {}, set(), 0, 0
    for line in lines:
        try:
            r = json.loads(line)
            if str(UUID(str(r["observer_id"]))) != r["observer_id"] or str(UUID(str(r["pass_id"]))) != r["pass_id"]:
                raise ValueError("invalid_identity")
            if (set(r) != FIELDS or r["schema"] != "genesis-supervisor-pass-v1" or r["experiment_evidence"] is not False
                    or r["activity"] != "intelligence-execution-v2" or r["phase"] not in {"START", "FINISH", "RAISED"}
                    or r["event_id"] != f"{r['pass_id']}:{r['phase']}" or r["clock_owner"] != "HOST_UTC_SUPERVISOR"
                    or r["wall_clock_order"] not in {"UNAVAILABLE", "ORDERED", "REGRESSION"}
                    or type(r["supervisor_pid"]) is not int or r["supervisor_pid"] <= 0):
                raise ValueError("invalid_metadata")
            if r["observed_at"] is not None and timestamp(lambda: datetime.fromisoformat(r["observed_at"])) != r["observed_at"]:
                raise ValueError("invalid_clock")
            if r["elapsed_sec"] is not None and (type(r["elapsed_sec"]) not in {int, float} or not math.isfinite(r["elapsed_sec"]) or r["elapsed_sec"] < 0):
                raise ValueError("invalid_duration")
            if r["return_code"] is not None and type(r["return_code"]) is not int:
                raise ValueError("invalid_exit")
            if r["event_id"] in seen:
                duplicates += 1
                if seen[r["event_id"]] != r:
                    conflicts.add(r["event_id"])
                continue
            seen[r["event_id"]] = r
            events.append(r)
        except (ValueError, TypeError, KeyError):
            invalid += 1
    events = [r for r in events if r["event_id"] not in conflicts]
    return {"status": "OBSERVED", "events": events[-limit:], "bytes_read": len(raw),
            "truncated": bool(offset or len(events) > limit), "invalid_lines": invalid, "duplicate_events": duplicates,
            "conflicting_event_ids": len(conflicts),
            "downtime": "UNESTABLISHED", "interpretation": "SUPERVISOR_BOUNDARIES_NOT_INGESTION_OR_EXPERIMENT_SESSIONS"}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(read_observations(root / "logs/v2-pass-provenance.jsonl"), indent=2))
