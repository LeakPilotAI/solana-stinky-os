"""Start the Genesis paper-only runtime as one detached, restartable local worker."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, timeout=5)
        return str(pid) in (r.stdout or "") and "No tasks" not in (r.stdout or "")
    except Exception:
        return False


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    pid_file = logs / "stinky-pids.txt"
    if pid_file.is_file():
        for line in pid_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("paper-runtime="):
                try:
                    pid = int(line.split("=", 1)[1])
                except ValueError:
                    pid = 0
                if _alive(pid):
                    print(f"  paper-runtime already running pid {pid}")
                    return 0
    pyw = root / ".venv" / "Scripts" / "pythonw.exe"
    pye = root / ".venv" / "Scripts" / "python.exe"
    exe = str(pyw if pyw.is_file() else pye if pye.is_file() else sys.executable)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "services" / "api" / "src") + ";" + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    log = open(logs / "paper-runtime.log", "a", encoding="utf-8", errors="replace")
    flags = 0x08000000 | 0x00000200 | 0x01000000 if os.name == "nt" else 0
    proc = subprocess.Popen(
        [exe, "-m", "stinky_api.paper_runtime_worker"], cwd=str(root), env=env,
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        creationflags=flags,
    )
    with pid_file.open("a", encoding="ascii") as f:
        f.write(f"paper-runtime={proc.pid}\n")
    print(f"  paper-runtime PID {proc.pid} (paper only; no RPC/signing/orders)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
