# Allowlisted Genesis service runner. Python, not PowerShell (Defender AMSI).
# Started by scripts\start-genesis-svc.cmd (cmd START /MIN).
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from genesis_runtime import (  # noqa: E402
    MAX_RESTARTS,
    record_restart,
    should_restart,
    system_state,
    write_state,
)

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

GENESIS_CONTAINERS = (
    "stinky-postgres",
    "stinky-redis",
    "stinky-minio",
    "stinky-minio-init",
)

WATCH_CONTAINERS = (
    "stinky-postgres",
    "stinky-redis",
    "stinky-minio",
)

CORE_HEALTH = (
    ("event-log", 8002, "http://127.0.0.1:8002/health"),
    ("api", 8010, "http://127.0.0.1:8010/health"),
    ("web", 3000, "http://127.0.0.1:3000/operator"),
)

# The API can remain alive after the Windows asyncio listener has died (WinError 64).
# Give startup plenty of time and require a sustained health loss before recycling.
API_HEALTH_POLL_SECONDS = 2.0
API_STARTUP_GRACE_SECONDS = 60.0
API_HEALTH_FAILURE_GRACE_SECONDS = 30.0
API_HEALTH_RECYCLE_EXIT = 86


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


def find_node() -> str | None:
    import shutil

    hit = shutil.which("node") or shutil.which("node.exe")
    if hit:
        return hit
    pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    la = Path(os.environ.get("LOCALAPPDATA", ""))
    for p in (pf / "nodejs" / "node.exe", la / "Programs" / "nodejs" / "node.exe"):
        if p.is_file():
            return str(p)
    return None


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

    def utc_stamp() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def append_log(message: str) -> None:
        with log.open("a", encoding="utf-8", errors="replace") as f:
            f.write(message)
            if not message.endswith("\n"):
                f.write("\n")
            f.flush()

    stamp = "[" + utc_stamp() + "] start pid=" + str(os.getpid())
    print("=== %s pid=%s" % (name, os.getpid()), flush=True)
    append_log(stamp)

    def http_ok(url: str, timeout: float = 2.5) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return 200 <= int(resp.status) < 600
        except Exception:
            return False

    def terminate_owned_child(proc: subprocess.Popen[str], reason: str) -> None:
        """Terminate only the child process tree launched by this Genesis supervisor."""
        if proc.poll() is not None:
            return
        append_log("[%s] %s recycling child pid=%s reason=%s" % (utc_stamp(), name, proc.pid, reason))
        if os.name == "nt":
            # First try a non-forceful tree termination. If Windows leaves the wedged
            # child alive, force only this exact Genesis child tree. Never Docker.
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T"],
                    capture_output=True,
                    timeout=8,
                    check=False,
                )
            except (subprocess.SubprocessError, OSError):
                pass
            try:
                proc.wait(timeout=5)
                return
            except subprocess.TimeoutExpired:
                pass
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
                return
            except (subprocess.TimeoutExpired, OSError):
                try:
                    proc.kill()
                except OSError:
                    pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            append_log("[%s] %s child pid=%s resisted termination" % (utc_stamp(), name, proc.pid))

    def run(
        cmd: list[str],
        cwd: Path | None = None,
        health_url: str | None = None,
    ) -> int:
        flags = 0
        startupinfo = None
        if os.name == "nt":
            flags = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd or root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            creationflags=flags,
            startupinfo=startupinfo,
        )
        assert proc.stdout is not None

        def pump_output() -> None:
            try:
                with log.open("a", encoding="utf-8", errors="replace") as f:
                    for line in proc.stdout:
                        sys.stdout.write(line)
                        sys.stdout.flush()
                        f.write(line)
                        f.flush()
            except (OSError, ValueError):
                pass

        reader = threading.Thread(target=pump_output, name="%s-log-pump" % name, daemon=True)
        reader.start()

        if not health_url:
            code = int(proc.wait())
            reader.join(timeout=3)
            return code

        started = time.monotonic()
        seen_healthy = False
        unhealthy_since: float | None = None
        while proc.poll() is None:
            now = time.monotonic()
            healthy = http_ok(health_url, 2.5)
            if healthy:
                if not seen_healthy:
                    append_log("[%s] %s health watchdog armed pid=%s" % (utc_stamp(), name, proc.pid))
                seen_healthy = True
                unhealthy_since = None
            elif seen_healthy:
                if unhealthy_since is None:
                    unhealthy_since = now
                elif now - unhealthy_since >= API_HEALTH_FAILURE_GRACE_SECONDS:
                    reason = "health endpoint down for %.0fs after becoming healthy" % (
                        now - unhealthy_since
                    )
                    terminate_owned_child(proc, reason)
                    reader.join(timeout=3)
                    return API_HEALTH_RECYCLE_EXIT
            elif now - started >= API_STARTUP_GRACE_SECONDS:
                reason = "health endpoint never became ready within %.0fs" % API_STARTUP_GRACE_SECONDS
                terminate_owned_child(proc, reason)
                reader.join(timeout=3)
                return API_HEALTH_RECYCLE_EXIT
            time.sleep(API_HEALTH_POLL_SECONDS)

        code = int(proc.wait())
        reader.join(timeout=3)
        return code

    def core_url(svc_name: str) -> str | None:
        for n, _port, url in CORE_HEALTH:
            if n == svc_name:
                return url
        return None

    def run_supervised(cmd: list[str], cwd: Path | None = None) -> int:
        """Restart on crash or sustained API health loss with a cap. Never storm."""
        delay = 5
        last = 0
        history: list[float] = []
        healthy_url = core_url(name)
        # The proven Windows dead-listener failure is API-specific. Keep this repair
        # narrow; event-log/web retain their existing exit-based supervision.
        watched_url = healthy_url if name == "api" else None
        while True:
            last = run(cmd, cwd, health_url=watched_url)
            if healthy_url and http_ok(healthy_url):
                msg = "[%s] %s exited %s but port is healthy, not spawning another\n" % (
                    utc_stamp(),
                    name,
                    last,
                )
                sys.stdout.write(msg)
                sys.stdout.flush()
                append_log(msg)
                return 0
            history = record_restart(history)
            ok_restart, phase = should_restart(history)
            if not ok_restart:
                msg = "[%s] %s FAILED after %s restarts in 15m, not looping\n" % (
                    utc_stamp(),
                    name,
                    MAX_RESTARTS,
                )
                sys.stdout.write(msg)
                sys.stdout.flush()
                append_log(msg)
                dump_runtime("FAILED")
                return last or 1
            msg = "[%s] %s exited %s, %s, restart in %ss\n" % (
                utc_stamp(),
                name,
                last,
                phase,
                delay,
            )
            sys.stdout.write(msg)
            sys.stdout.flush()
            append_log(msg)
            dump_runtime(phase)
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
                utc_stamp(),
                last,
                i,
                attempts,
                delay,
            )
            sys.stdout.write(msg)
            sys.stdout.flush()
            append_log(msg)
            if i < attempts:
                time.sleep(delay)
                delay = min(delay * 2, 60)
        return last

    def find_docker_bin() -> str | None:
        import shutil

        hit = shutil.which("docker") or shutil.which("docker.exe")
        if hit:
            return hit
        p = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe"
        return str(p) if p.is_file() else None

    def dump_runtime(phase: str = "") -> None:
        core: dict[str, str] = {}
        for n, _port, url in CORE_HEALTH:
            core[n] = "UP" if http_ok(url, 3.0) else "DOWN"
        payload = {
            "as_of": utc_stamp(),
            "system": phase or system_state(core),
            "services": core,
            "watch": list(WATCH_CONTAINERS),
            "note": "HTTP health only. UNKNOWN is not UP. Gate 1 is not here.",
        }
        try:
            write_state(log_dir / "runtime-state.json", payload)
        except OSError:
            pass

    def listen_pid(port: int) -> int:
        try:
            out = subprocess.check_output(["netstat", "-ano"], text=True, errors="replace", timeout=8)
        except (subprocess.SubprocessError, OSError):
            return 0
        for line in out.splitlines():
            if "LISTENING" not in line.upper():
                continue
            if not re.search(r":%d(\s|$)" % port, line):
                continue
            parts = line.split()
            if parts and parts[-1].isdigit():
                return int(parts[-1])
        return 0

    def hidden_run(cmd: list[str], timeout: int = 40) -> None:
        flags = 0
        startupinfo = None
        if os.name == "nt":
            flags = 0x08000000
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        try:
            subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                creationflags=flags,
                startupinfo=startupinfo,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass

    def watchdog_tick() -> None:
        """If Postgres/Redis/MinIO were stopped, start them. No compose up. No consoles. Never ATLAS.

        project-genesis compose up is only at desktop start.
        """
        docker = find_docker_bin()
        if not docker:
            return
        hidden_run([docker, "start", *WATCH_CONTAINERS], timeout=40)

    url_now = core_url(name)
    if url_now and http_ok(url_now):
        msg = "[%s] %s already healthy, not starting another copy\n" % (
            utc_stamp(),
            name,
        )
        sys.stdout.write(msg)
        sys.stdout.flush()
        append_log(msg)
        return 0

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
            node = find_node()
            nxt = root / "apps" / "web" / "node_modules" / "next" / "dist" / "bin" / "next"
            if node and nxt.is_file():
                code = run_supervised(
                    [node, str(nxt), "dev", "-p", "3000", "-H", "127.0.0.1"],
                    cwd=root / "apps" / "web",
                )
            else:
                npm = find_npm() or "npm"
                code = run_supervised(
                    [npm, "run", "dev", "--", "-p", "3000", "-H", "127.0.0.1"],
                    cwd=root / "apps" / "web",
                )
        elif name == "maintain":
            next_job = 0.0
            while True:
                try:
                    watchdog_tick()
                    dump_runtime()
                except Exception as exc:
                    msg = "[%s] watchdog error %s\n" % (utc_stamp(), str(exc)[:200])
                    sys.stdout.write(msg)
                    sys.stdout.flush()
                    append_log(msg)
                now = time.time()
                if now >= next_job:
                    run_job_with_retry([py, "-m", "post_migration.cli", "learn-success"])
                    run_job_with_retry([py, "-m", "post_migration.cli", "recompute-performance"])
                    next_job = time.time() + 21600
                time.sleep(60)
    finally:
        append_log("[%s] exit LASTEXITCODE=%s" % (utc_stamp(), code))
    return code


if __name__ == "__main__":
    sys.exit(main())
