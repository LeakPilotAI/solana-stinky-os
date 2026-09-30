"""Start Genesis paper-only producer + runtime workers detached on Windows."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# The policy runtime is the registry-authoritative wrapper around
# stinky_api.prospective_paper_intake_producer; the underlying producer remains unchanged.
WORKERS = ("paper-intake-producer", "paper-runtime")
STATE_MAX_AGE_SECONDS = 150.0
STARTUP_PROOF_SECONDS = 12.0


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, timeout=5)
        return str(pid) in (r.stdout or "") and "No tasks" not in (r.stdout or "")
    except Exception:
        return False


def _known_pids(pid_file: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    if not pid_file.is_file():
        return out
    for line in pid_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line:
            continue
        name, raw = line.split("=", 1)
        try:
            out[name.strip()] = int(raw.strip())
        except ValueError:
            continue
    return out


def _write_pids(pid_file: Path, known: dict[str, int]) -> None:
    lines = [f"{name}={pid}" for name, pid in known.items() if int(pid) > 0]
    tmp = pid_file.with_suffix(pid_file.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="ascii")
    tmp.replace(pid_file)


def _parse_utc(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _owned_supervisor(pid: int, name: str, logs: Path, *, now: datetime | None = None) -> bool:
    """Accept an existing PID only when a fresh Genesis supervisor heartbeat owns it."""
    if not _alive(pid):
        return False
    state_path = logs / f"runtime-state-{name}.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(state, dict):
        return False
    if state.get("service") != name or state.get("supervisor_pid") != pid:
        return False
    if str(state.get("supervisor_phase") or "").upper() == "FAILED":
        return False
    observed = _parse_utc(state.get("as_of"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if observed is None:
        return False
    age = (current - observed).total_seconds()
    return -5.0 <= age <= STATE_MAX_AGE_SECONDS


def _tail_service_log(name: str, logs: Path, lines: int = 20) -> str:
    path = logs / f"{name}.log"
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-max(1, int(lines)):])


def _wait_for_owned_supervisor(proc: subprocess.Popen, name: str, logs: Path) -> bool:
    deadline = time.monotonic() + STARTUP_PROOF_SECONDS
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        if _owned_supervisor(int(proc.pid), name, logs):
            return True
        time.sleep(0.25)
    return False


def _terminate_started_tree(proc: subprocess.Popen) -> None:
    """Stop only the supervisor tree this starter launched."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=8,
                check=False,
            )
        except (subprocess.SubprocessError, OSError):
            pass
    else:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            try:
                proc.kill()
            except OSError:
                pass


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    pid_file = logs / "stinky-pids.txt"
    known = _known_pids(pid_file)
    pyw = root / ".venv" / "Scripts" / "pythonw.exe"
    pye = root / ".venv" / "Scripts" / "python.exe"
    exe = str(pyw if pyw.is_file() else pye if pye.is_file() else sys.executable)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "services" / "api" / "src") + ";" + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    flags = 0x08000000 | 0x00000200 | 0x01000000 if os.name == "nt" else 0
    supervisor = root / "scripts" / "run_genesis_service.py"
    failed = False

    for name in WORKERS:
        old = known.get(name, 0)
        if _owned_supervisor(old, name, logs):
            print(f"  {name} already supervised pid {old}")
            continue
        if old:
            print(f"  {name} stale/unowned pid {old}; starting a verified Genesis supervisor")
        known.pop(name, None)

        log = open(logs / (name + ".log"), "a", encoding="utf-8", errors="replace")
        try:
            proc = subprocess.Popen(
                [exe, str(supervisor), "--name", name],
                cwd=str(root),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
        finally:
            log.close()

        if not _wait_for_owned_supervisor(proc, name, logs):
            print(f"  {name} STARTUP FAILED: supervisor ownership/heartbeat was not proven")
            tail = _tail_service_log(name, logs)
            if tail:
                print(f"  {name} recent log tail:\n{tail}")
            state_path = logs / f"runtime-state-{name}.json"
            if state_path.is_file():
                try:
                    print(
                        f"  {name} runtime state: "
                        + state_path.read_text(encoding="utf-8", errors="replace")[-2000:]
                    )
                except OSError:
                    pass
            _terminate_started_tree(proc)
            failed = True
            continue

        known[name] = int(proc.pid)
        _write_pids(pid_file, known)
        print(f"  {name} PID {proc.pid} VERIFIED (paper only; no RPC/signing/orders)")

    _write_pids(pid_file, known)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
