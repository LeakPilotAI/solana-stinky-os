# Allowlisted Genesis service runner. Python, not PowerShell (Defender AMSI).
# Started by scripts\start-genesis-svc.cmd (cmd START /MIN).
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

NAMES = (
    "event-log",
    "api",
    "sentinel",
    "discord",
    "collector",
    "entities",
    "web",
    "maintain",
)


def restore_search_path() -> None:
    parts: list[str] = []
    try:
        import winreg

        for hive, sub in (
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
            (winreg.HKEY_CURRENT_USER, "Environment"),
        ):
            try:
                with winreg.OpenKey(hive, sub) as key:
                    val, _ = winreg.QueryValueEx(key, "Path")
                    if val:
                        parts.append(str(val))
            except OSError:
                pass
    except Exception:
        pass
    if os.environ.get("PATH"):
        parts.append(os.environ["PATH"])
    if parts:
        os.environ["PATH"] = ";".join(parts)
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    la = os.environ.get("LOCALAPPDATA", "")
    extras = [
        str(Path(pf) / "Git" / "cmd"),
        str(Path(pf) / "Docker" / "Docker" / "resources" / "bin"),
        str(Path(pf) / "nodejs"),
        str(Path(la) / "Programs" / "nodejs") if la else "",
        str(Path(os.environ.get("APPDATA", "")) / "npm"),
    ]
    path = os.environ.get("PATH", "")
    for d in extras:
        if d and os.path.isdir(d) and d.lower() not in path.lower():
            path = d + ";" + path
    os.environ["PATH"] = path


def find_npm() -> str | None:
    import shutil

    hit = shutil.which("npm") or shutil.which("npm.cmd")
    if hit:
        return hit
    pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    la = Path(os.environ.get("LOCALAPPDATA", ""))
    for p in (pf / "nodejs" / "npm.cmd", la / "Programs" / "nodejs" / "npm.cmd"):
        if p.is_file():
            return str(p)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, choices=NAMES)
    args = parser.parse_args()
    name = args.name

    restore_search_path()
    root = Path(__file__).resolve().parent.parent
    if not (root / "docker-compose.yml").is_file():
        root = Path(r"D:\Work\Project-Genesis")
    os.chdir(root)
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / (name + ".log")
    venv_py = root / ".venv" / "Scripts" / "python.exe"
    py = str(venv_py) if venv_py.is_file() else sys.executable

    py_path = ";".join(
        str(root / p)
        for p in (
            r"packages\stinky-core\src",
            r"services\event-log\src",
            r"services\api\src",
            r"services\sentinel\src",
            r"services\discord-bot\src",
            r"services\post-migration-collector\src",
            r"services\entity-resolver\src",
        )
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = py_path + ";" + env.get("PYTHONPATH", "")
    env["BROWSER"] = "none"
    env["STINKY_ROOT"] = str(root)
    env["PYTHONUNBUFFERED"] = "1"

    stamp = "[" + datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "] start pid=" + str(os.getpid())
    print("=== %s pid=%s" % (name, os.getpid()), flush=True)
    with log.open("a", encoding="utf-8", errors="replace") as f:
        f.write(stamp + "\n")

    def run(cmd: list[str], cwd: Path | None = None) -> int:
        with log.open("a", encoding="utf-8", errors="replace") as f:
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd or root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                f.write(line)
                f.flush()
            return int(proc.wait())

    def run_supervised(cmd: list[str], cwd: Path | None = None) -> int:
        """Long-running services: if Windows/Docker drops the NIC, restart. Do not exit the OS."""
        delay = 5
        last = 0
        while True:
            last = run(cmd, cwd)
            msg = "[%s] %s exited %s, restart in %ss\n" % (
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                name,
                last,
                delay,
            )
            sys.stdout.write(msg)
            sys.stdout.flush()
            with log.open("a", encoding="utf-8", errors="replace") as f:
                f.write(msg)
            time.sleep(delay)
            delay = min(delay * 2, 60)

    def run_job_with_retry(cmd: list[str], attempts: int = 3) -> int:
        delay = 15
        last = 1
        for i in range(1, attempts + 1):
            last = run(cmd)
            if last == 0:
                return 0
            msg = "[%s] maintain job failed exit=%s attempt=%s/%s, retry in %ss\n" % (
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                last,
                i,
                attempts,
                delay,
            )
            sys.stdout.write(msg)
            sys.stdout.flush()
            with log.open("a", encoding="utf-8", errors="replace") as f:
                f.write(msg)
            if i < attempts:
                time.sleep(delay)
                delay = min(delay * 2, 60)
        return last

    code = 0
    try:
        if name == "event-log":
            code = run_supervised([py, "-m", "uvicorn", "event_log.api:app", "--port", "8002", "--host", "127.0.0.1"])
        elif name == "api":
            code = run_supervised([py, "-m", "stinky_api.cli"])
        elif name == "sentinel":
            code = run_supervised([py, "-m", "sentinel.cli"])
        elif name == "discord":
            code = run_supervised([py, "-m", "discord_bot.cli"])
        elif name == "collector":
            code = run_supervised([py, "-m", "post_migration.cli"])
        elif name == "entities":
            code = run_supervised([py, "-m", "entity_resolver.cli"])
        elif name == "web":
            npm = find_npm() or "npm"
            code = run_supervised([npm, "run", "dev", "--", "-p", "3000", "-H", "127.0.0.1"], cwd=root / "apps" / "web")
        elif name == "maintain":
            while True:
                run_job_with_retry([py, "-m", "post_migration.cli", "learn-success"])
                run_job_with_retry([py, "-m", "post_migration.cli", "recompute-performance"])
                time.sleep(21600)
    finally:
        with log.open("a", encoding="utf-8", errors="replace") as f:
            f.write(
                "["
                + datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                + "] exit LASTEXITCODE="
                + str(code)
                + "\n"
            )
    return code


if __name__ == "__main__":
    sys.exit(main())
