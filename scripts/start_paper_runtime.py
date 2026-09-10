"""Start Genesis paper-only producer + runtime workers detached on Windows."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# The policy runtime is the registry-authoritative wrapper around
# stinky_api.prospective_paper_intake_producer; the underlying producer remains unchanged.
WORKERS = (
    ("paper-intake-producer", "stinky_api.prospective_paper_policy_runtime"),
    ("paper-runtime", "stinky_api.paper_runtime_worker"),
)


def _alive(pid: int) -> bool:
    if pid <= 0:
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
    started: list[tuple[str, int]] = []
    for name, module in WORKERS:
        old = known.get(name, 0)
        if _alive(old):
            print(f"  {name} already running pid {old}")
            continue
        log = open(logs / (name + ".log"), "a", encoding="utf-8", errors="replace")
        proc = subprocess.Popen([exe, "-m", module], cwd=str(root), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        started.append((name, proc.pid))
        print(f"  {name} PID {proc.pid} (paper only; no RPC/signing/orders)")
    if started:
        with pid_file.open("a", encoding="ascii") as f:
            for name, pid in started:
                f.write(f"{name}={pid}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
