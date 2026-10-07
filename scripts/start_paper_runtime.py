"""Start Genesis paper-only producer + runtime workers detached on Windows."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
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
    # Use the native Win32 process API for bounded, direct liveness proof.
    # tasklist is an external process and can itself stall for seconds, which
    # must never consume the supervisor ownership-proof window.
    try:
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return int(exit_code.value) == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError, ValueError):
        return False


def _windows_process_started_at(pid: int) -> datetime | None:
    """Return native Windows process creation time for this exact PID instance."""
    if os.name != "nt" or pid <= 0:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return None
        try:
            created = wintypes.FILETIME()
            exited = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return None
            ticks = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
            unix_seconds = (ticks - 116444736000000000) / 10_000_000
            return datetime.fromtimestamp(unix_seconds, tz=timezone.utc)
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError, OverflowError, ValueError):
        return None


def _legacy_supervisor_instance_identity(pid: int, name: str, logs: Path) -> bool:
    """Prove a pre-token supervisor by PID + state + log + native creation time."""
    if os.name != "nt" or pid <= 0 or name not in WORKERS:
        return False
    state_path = logs / f"runtime-state-{name}.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(state, dict):
        return False
    if state.get("service") != name or int(state.get("supervisor_pid") or 0) != int(pid):
        return False
    recorded = _parse_utc(state.get("supervisor_started_at"))
    actual = _windows_process_started_at(pid)
    if recorded is None or actual is None:
        return False
    # run_genesis_service records whole-second UTC immediately after Python starts.
    if abs((actual - recorded).total_seconds()) > 5.0:
        return False
    log_path = logs / f"{name}.log"
    try:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    stamp = recorded.strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"[{stamp}] start pid={int(pid)}" in log_text


def _windows_supervisor_identity(pid: int, name: str) -> bool:
    """Prove a live Windows PID is this exact Genesis service supervisor."""
    if os.name != "nt" or pid <= 0 or not name:
        return False
    escaped = str(int(pid))
    ps = (
        "$ErrorActionPreference='Stop'; "
        f"$p=Get-CimInstance Win32_Process -Filter \"ProcessId={escaped}\"; "
        "if ($null -eq $p) { exit 3 }; "
        "[Console]::Out.Write($p.CommandLine)"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    if result.returncode != 0:
        return False
    command = (result.stdout or "").replace("/", "\\").lower()
    return (
        "run_genesis_service.py" in command
        and "--name" in command
        and name.lower() in command
    )


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


def _wait_for_owned_supervisor(
    proc: subprocess.Popen, name: str, logs: Path, launch_token: str
) -> int:
    deadline = time.monotonic() + STARTUP_PROOF_SECONDS
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return 0
        try:
            state = json.loads((logs / f"runtime-state-{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        if isinstance(state, dict) and launch_token and state.get("supervisor_launch_token") == launch_token:
            pid = state.get("supervisor_pid")
            if type(pid) is int and pid > 0 and _owned_supervisor(pid, name, logs):
                return pid
        time.sleep(0.25)
    return 0


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
        launch_token = uuid.uuid4().hex
        worker_env = {**env, "GENESIS_SUPERVISOR_LAUNCH_TOKEN": launch_token}
        try:
            proc = subprocess.Popen(
                [exe, str(supervisor), "--name", name],
                cwd=str(root),
                env=worker_env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
        finally:
            log.close()

        owned_pid = _wait_for_owned_supervisor(proc, name, logs, launch_token)
        if not owned_pid:
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

        known[name] = owned_pid
        _write_pids(pid_file, known)
        print(f"  {name} PID {owned_pid} VERIFIED (paper only; no RPC/signing/orders)")

    _write_pids(pid_file, known)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
