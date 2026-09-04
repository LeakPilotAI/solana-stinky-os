# start_genesis.py - desktop start for Genesis. Not PowerShell (Defender AMSI).
# Start-Stinky-OS.cmd runs this file. Gate 1 is $33k / 5m, clamp $200k.
from __future__ import annotations

# Current Gate 1 investigation threshold. Not a buy signal.
GATE1_VOLUME_5M_USD = 33_000.0
GATE1_VOLUME_CALIBRATION_MAX_USD = 200_000.0

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

REPO = "https://github.com/LeakPilotAI/solana-stinky-os.git"
OPERATOR_ROOT = Path(r"D:\Work\Project-Genesis")
SERVICES = (
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


def script_root() -> Path:
    return Path(__file__).resolve().parent


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
        str(Path(pf) / "Git" / "bin"),
        str(Path(pf) / "Docker" / "Docker" / "resources" / "bin"),
        str(Path(pf) / "nodejs"),
        str(Path(la) / "Programs" / "Git" / "cmd") if la else "",
        str(Path(la) / "Programs" / "nodejs") if la else "",
        str(Path(os.environ.get("APPDATA", "")) / "npm"),
        str(Path(la) / "Programs" / "Python" / "Launcher") if la else "",
        str(Path(la) / "Programs" / "Python" / "Python312") if la else "",
        str(Path(la) / "Programs" / "Python" / "Python312" / "Scripts") if la else "",
        r"C:\Python312",
        r"C:\Python312\Scripts",
    ]
    path = os.environ.get("PATH", "")
    for d in extras:
        if d and os.path.isdir(d) and d.lower() not in path.lower():
            path = d + ";" + path
    os.environ["PATH"] = path


def resolve_root() -> Path:
    here = script_root()
    if (here / "docker-compose.yml").is_file():
        return here
    if (OPERATOR_ROOT / "docker-compose.yml").is_file():
        return OPERATOR_ROOT
    return here


ROOT = resolve_root()
LOG_DIR = ROOT / "logs"
PID_FILE = LOG_DIR / "stinky-pids.txt"
STARTUP_LOG = LOG_DIR / "startup.log"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
CMD_EXE = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"
HEALTH: dict[str, str] = {}
FAILED = False


def which_exe(name: str, extras: list[Path] | None = None) -> str | None:
    hit = shutil.which(name)
    if hit:
        return hit
    if os.name == "nt" and not name.lower().endswith(".exe") and not name.lower().endswith(".cmd"):
        hit = shutil.which(name + ".exe") or shutil.which(name + ".cmd")
        if hit:
            return hit
    for p in extras or []:
        if p.is_file():
            return str(p)
    return None


def find_docker() -> str | None:
    pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    return which_exe("docker", [pf / "Docker" / "Docker" / "resources" / "bin" / "docker.exe"])


def find_npm() -> str | None:
    pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    la = Path(os.environ.get("LOCALAPPDATA", ""))
    return which_exe(
        "npm",
        [pf / "nodejs" / "npm.cmd", la / "Programs" / "nodejs" / "npm.cmd"],
    )


DOCKER = None
NPM = None


def configure_stdio() -> None:
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def say(msg: str) -> None:
    print(msg, flush=True)


def step(msg: str) -> None:
    say("")
    say(msg)


def ok(msg: str) -> None:
    say("  " + msg)


def warn(msg: str) -> None:
    say("  " + msg)


def redact(line: str) -> str:
    return re.sub(
        r"(?i)((?:API_KEY|TOKEN|SECRET|PASSWORD|PRIVATE_KEY|DISCORD_TOKEN)\s*=\s*).+",
        r"\1***",
        line,
    )


def log_line(component: str, result: str, command: str = "", pid_value: str = "", reason: str = "") -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = [ts, component, result]
    if pid_value:
        parts.append("pid=" + pid_value)
    if command:
        parts.append("cmd=" + redact(command))
    if reason:
        parts.append("reason=" + redact(reason))
    STARTUP_LOG.parent.mkdir(parents=True, exist_ok=True)
    with STARTUP_LOG.open("a", encoding="utf-8", errors="replace") as f:
        f.write("  ".join(parts) + "\n")


def fail(name: str, status: str, reason: str, log_file: str = "", next_step: str = "") -> None:
    global FAILED
    FAILED = True
    HEALTH[name] = status
    say("")
    say("GENESIS STARTUP FAILED")
    say("Component: " + name)
    say("Status:    " + status)
    say("Reason:    " + reason)
    if log_file:
        say("Log:       " + log_file)
    if next_step:
        say("Next:      " + next_step)
    log_line(name, status, reason=reason)


def http_ok(url: str, timeout: float = 4.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= int(resp.status) < 500
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def wait_http(url: str, seconds: int, label: str = "") -> bool:
    deadline = time.time() + seconds
    n = 0
    while time.time() < deadline:
        if http_ok(url, 8):
            return True
        n += 1
        if label:
            say("  waiting %s (%ss)" % (label, n * 2))
        time.sleep(2)
    return False


def get_json(url: str):
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return None


def core_healthy() -> bool:
    return http_ok("http://127.0.0.1:8010/health", 4) and http_ok("http://127.0.0.1:3000/operator", 4)


def listen_pid(port: int) -> int:
    try:
        out = subprocess.check_output(["netstat", "-ano"], text=True, errors="replace", timeout=8)
    except (subprocess.SubprocessError, OSError):
        return 0
    needle = ":" + str(port) + " "
    for line in out.splitlines():
        if "LISTENING" not in line:
            continue
        if needle not in line and not re.search(r":%d\s+" % port, line):
            continue
        parts = line.split()
        if parts and parts[-1].isdigit():
            return int(parts[-1])
    return 0


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            r = subprocess.run(
                ["tasklist", "/FI", "PID eq %d" % pid],
                capture_output=True,
                text=True,
                timeout=5,
            )
            body = (r.stdout or "") + (r.stderr or "")
            return str(pid) in body and "No tasks" not in body
        except (subprocess.SubprocessError, OSError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def pid_from_log(name: str) -> int:
    log = LOG_DIR / (name + ".log")
    if not log.is_file():
        return 0
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    found = re.findall(r"start pid=(\d+)", text)
    return int(found[-1]) if found else 0


def list_win_processes() -> list[tuple[int, int, str, str]]:
    """(pid, parent_pid, name, commandline)."""
    ps = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    cmd = (
        "Get-CimInstance Win32_Process | ForEach-Object { "
        "'{0}\t{1}\t{2}\t{3}' -f $_.ProcessId, $_.ParentProcessId, $_.Name, "
        "(($_.CommandLine) -replace '[\\r\\n]',' ') }"
    )
    try:
        r = subprocess.run(
            [str(ps), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    rows: list[tuple[int, int, str, str]] = []
    for line in (r.stdout or "").splitlines():
        parts = line.split("\t", 3)
        if len(parts) < 3 or not parts[0].strip().isdigit():
            continue
        pid = int(parts[0].strip())
        ppid = int(parts[1].strip()) if parts[1].strip().isdigit() else 0
        name = parts[2].strip() if len(parts) > 2 else ""
        cl = parts[3] if len(parts) > 3 else ""
        rows.append((pid, ppid, name, cl))
    return rows


def is_launcher_process(name: str, cmdline: str) -> bool:
    n = (name or "").lower()
    if n in (
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "conhost.exe",
        "openconsole.exe",
        "windowsterminal.exe",
        "explorer.exe",
    ):
        return True
    cl = (cmdline or "").lower()
    needles = (
        "start-stinky-os.cmd",
        "stop-stinky-os.cmd",
        "apply-launcher.ps1",
        "apply-launcher.cmd",
        "apply-refresh.ps1",
        "install-desktop-shortcut.ps1",
        "start_genesis.py",
    )
    return any(s in cl for s in needles)


def genesis_owned(pid: int, name: str, cmdline: str) -> bool:
    if pid <= 0:
        return False
    if is_launcher_process(name, cmdline):
        return False
    n = (name or "").lower()
    if n.startswith("docker") or "com.docker" in n:
        return False
    c = cmdline or ""
    if not c:
        return False
    cl = c.lower()
    if "docker desktop" in cl or "dockerd" in cl:
        return False
    root_s = str(ROOT).lower()
    path_hit = (
        root_s in cl
        or "project-genesis" in cl
        or "solana-stinky-os" in cl
        or "run_genesis_service.py" in cl
        or "start-genesis-svc.cmd" in cl
    )
    if not path_hit:
        return False
    markers = (
        "uvicorn",
        "event_log",
        "stinky_api",
        "stinky_core",
        "sentinel.cli",
        "discord_bot",
        "post_migration",
        "entity_resolver",
        "run_genesis_service.py",
        "start-genesis-svc",
        "npm run dev",
        "next-server",
        "next dev",
        "genesis-event-log",
        "genesis-api",
        "genesis-sentinel",
        "genesis-discord",
        "genesis-collector",
        "genesis-entities",
        "genesis-web",
        "genesis-maintain",
    )
    return any(m in cl for m in markers)


def kill_pid(pid: int, name: str = "") -> None:
    if pid <= 0:
        return
    if is_launcher_process(name, ""):
        say("  skip pid %d (%s is a launcher host)" % (pid, name or "?"))
        return
    say("  taskkill /PID %d /F" % pid)
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=10)
    except (subprocess.SubprocessError, OSError):
        pass
    log_line("pid", "killed", pid_value=str(pid))


def stop_owned_instance() -> None:
    """Kill leftover Genesis-owned apps, then stop Genesis compose. Never ATLAS / Docker Desktop / this window."""
    step("[0] stop leftover Genesis processes (owned only)")
    me = os.getpid()
    parent = os.getppid()
    say("  launcher pid=%d parent=%d (never killed)" % (me, parent))
    procs = list_win_processes()
    parent_of = {p: pp for p, pp, n, c in procs}
    skip = {me, parent, 0}
    cur = me
    for _ in range(24):
        pp = parent_of.get(cur, 0)
        if pp <= 0 or pp in skip:
            break
        skip.add(pp)
        cur = pp
    by_pid = {p: (n, c) for p, pp, n, c in procs}

    def maybe_kill(pid: int) -> None:
        if pid in skip:
            return
        name, cl = by_pid.get(pid, ("", ""))
        if is_launcher_process(name, cl):
            say("  skip pid %d (launcher window)" % pid)
            return
        if name or cl:
            if not genesis_owned(pid, name, cl):
                say("  skip pid %d (not Genesis-owned)" % pid)
                log_line("pid", "skipped", pid_value=str(pid), reason="not Genesis-owned")
                return
        elif pid not in by_pid:
            return
        kill_pid(pid, name)
        skip.add(pid)

    if PID_FILE.is_file():
        try:
            for line in PID_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
                m = re.search(r"=(\d+)\s*$", line.strip()) or re.match(r"^(\d+)$", line.strip())
                if m:
                    maybe_kill(int(m.group(1)))
        except OSError:
            pass
        try:
            PID_FILE.unlink()
        except OSError:
            pass

    for pid, pp, name, cl in procs:
        if genesis_owned(pid, name, cl):
            maybe_kill(pid)

    for port in (8002, 8010, 3000):
        owner = listen_pid(port)
        if owner > 0:
            maybe_kill(owner)

    stop_genesis_containers()
    time.sleep(2)
    ok("previous Genesis instance stopped")
    log_line("launcher", "STOPPED")


def stop_genesis_containers() -> None:
    """Stop only named Genesis containers. Never ATLAS, never Docker Desktop, volumes kept."""
    docker = DOCKER or find_docker()
    if not docker:
        say("  docker.exe not found, skip container stop")
        log_line("docker-compose", "skipped", reason="docker.exe not found")
        return
    compose = ROOT / "docker-compose.yml"
    if compose.is_file():
        say("  docker compose stop (Genesis project only, volumes kept)")
        subprocess.run(
            [
                docker,
                "compose",
                "-p",
                "project-genesis",
                "-f",
                str(compose),
                "--project-directory",
                str(ROOT),
                "stop",
            ],
            cwd=str(ROOT),
            capture_output=True,
            timeout=90,
        )
    say("  docker stop " + " ".join(GENESIS_CONTAINERS))
    try:
        r = subprocess.run(
            [docker, "stop", "--timeout", "10", *GENESIS_CONTAINERS],
            capture_output=True,
            timeout=90,
            text=True,
        )
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        if out:
            for line in out.splitlines()[:8]:
                say("    " + line)
    except (subprocess.SubprocessError, OSError) as exc:
        say("  docker stop: %s" % exc)
    log_line("docker-compose", "stopped", reason="genesis containers only")


def clean_broken_dists() -> None:
    sp = ROOT / ".venv" / "Lib" / "site-packages"
    if not sp.is_dir():
        return
    removed = 0
    for p in list(sp.iterdir()):
        if not p.name.startswith("~"):
            continue
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            try:
                p.unlink()
            except OSError:
                pass
        removed += 1
    if removed:
        ok("removed %d broken pip leftover(s)" % removed)


def run_cmd(args: list[str], timeout: int | None = None, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        input=stdin,
        capture_output=True,
        timeout=timeout,
    )


def tail_run(args: list[str], last: int = 5, cwd: Path | None = None) -> int:
    p = subprocess.run(
        args,
        cwd=str(cwd or ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    out = (p.stdout or "") + (p.stderr or "")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    for ln in lines[-last:]:
        say("  " + ln)
    return int(p.returncode or 0)


def backup_env() -> Path | None:
    env_file = ROOT / ".env"
    bak = LOG_DIR / "env.backup"
    if env_file.is_file():
        shutil.copy2(env_file, bak)
        return bak
    return None


def restore_env(bak: Path | None) -> None:
    if bak and bak.is_file():
        shutil.copy2(bak, ROOT / ".env")


def sync_from_github(do_sync: bool, skip_sync: bool) -> None:
    if not do_sync or skip_sync or os.environ.get("STINKY_SKIP_SYNC") == "1":
        if skip_sync:
            warn("SkipSync - using files on disk")
        return
    bak = backup_env()
    try:
        if (ROOT / ".git").exists():
            step("[sync] git fetch + reset origin/main (keeps .env)")
            git = which_exe("git") or "git"
            subprocess.run([git, "-C", str(ROOT), "remote", "set-url", "origin", REPO], cwd=str(ROOT))
            subprocess.run([git, "-C", str(ROOT), "fetch", "origin"], cwd=str(ROOT))
            subprocess.run([git, "-C", str(ROOT), "reset", "--hard", "origin/main"], cwd=str(ROOT))
            subprocess.run([git, "-C", str(ROOT), "checkout", "-f", "-B", "main", "origin/main"], cwd=str(ROOT))
            head = subprocess.check_output([git, "-C", str(ROOT), "rev-parse", "--short", "HEAD"], text=True).strip()
            ok("tree = " + head)
            log_line("sync", "ok", command="git reset --hard origin/main")
        else:
            warn("folder is not a git clone - starting with files on disk. Use APPLY-refresh.ps1 to overwrite from GitHub.")
            log_line("sync", "skipped", reason="not a git clone")
    except Exception as exc:
        warn("sync failed: %s - starting with files on disk" % exc)
        log_line("sync", "failed", reason=str(exc))
    restore_env(bak)


def ensure_dotenv() -> None:
    env_file = ROOT / ".env"
    example = ROOT / ".env.example"
    if not env_file.is_file():
        if example.is_file():
            shutil.copy2(example, env_file)
            warn("created .env from .env.example - add Discord token locally if you want alerts")
    else:
        ok(".env present (secrets kept, not logged)")


def ensure_venv(skip_install: bool) -> None:
    if skip_install and VENV_PY.is_file():
        return
    if VENV_PY.is_file():
        try:
            r = subprocess.run(
                [str(VENV_PY), "-c", "import stinky_core, event_log, stinky_api"],
                capture_output=True,
                timeout=10,
            )
            if r.returncode == 0:
                ok("python packages already installed")
                return
        except (subprocess.TimeoutExpired, OSError):
            pass
    step("[deps] Python venv + editable installs")
    clean_broken_dists()
    if not VENV_PY.is_file():
        subprocess.check_call([sys.executable, "-m", "venv", str(ROOT / ".venv")])
    py = str(VENV_PY)
    tail_run([py, "-m", "pip", "install", "-U", "pip", "wheel", "hatchling"], last=3)
    pkgs = [
        r".\packages\stinky-core",
        r".\services\event-log",
        r".\services\api",
        r".\services\sentinel",
        r".\services\discord-bot",
        r".\services\post-migration-collector",
        r".\services\entity-resolver",
    ]
    for pkg in pkgs:
        say("  pip install -e " + pkg)
        tail_run([py, "-m", "pip", "install", "-e", pkg], last=2)
    ok("python packages installed")
    log_line("venv", "ok", command="pip install -e packages/services")


def ensure_web() -> None:
    web = ROOT / "apps" / "web"
    if not (web / "package.json").is_file():
        return
    step("[deps] npm install (web)")
    npm = NPM or find_npm()
    if not npm:
        fail("FRONTEND", "DOWN", "npm not found after PATH restore", next_step="Install Node.js LTS, then double-click Genesis again.")
        raise RuntimeError("npm not found")
    code = tail_run([npm, "install", "--no-fund", "--no-audit"], last=5, cwd=web)
    if code != 0:
        warn("npm install exit %d (continuing)" % code)
    ok("web deps ready")
    log_line("web-deps", "ok", command=npm + " install")


def ensure_docker() -> None:
    global DOCKER
    step("[docker] compose up (Postgres 5433 / Redis 6380 / MinIO 9010)")
    docker = DOCKER or find_docker()
    DOCKER = docker
    if not docker:
        fail("Docker", "DOWN", "docker.exe not found after PATH restore", next_step="Install Docker Desktop, start it, then double-click Genesis again.")
        raise RuntimeError("Docker is not running.")
    info = subprocess.run([docker, "info"], capture_output=True, timeout=20)
    if info.returncode != 0:
        dd = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "Docker Desktop.exe"
        if dd.is_file():
            warn("starting Docker Desktop...")
            subprocess.Popen([str(dd)], cwd=str(dd.parent))
        for _ in range(40):
            time.sleep(3)
            info = subprocess.run([docker, "info"], capture_output=True, timeout=20)
            if info.returncode == 0:
                break
    info = subprocess.run([docker, "info"], capture_output=True, timeout=20)
    if info.returncode != 0:
        fail("Docker", "DOWN", "Docker is not running", next_step="Start Docker Desktop and double-click Genesis again.")
        raise RuntimeError("Docker is not running.")
    up = subprocess.run(
        [
            docker,
            "compose",
            "-p",
            "project-genesis",
            "-f",
            str(ROOT / "docker-compose.yml"),
            "up",
            "-d",
        ],
        cwd=str(ROOT),
        timeout=120,
    )
    say("  docker compose up -d exit %d" % (up.returncode or 0))
    log_line("docker", "started", command=docker + " compose up -d")

    def dockerexec(args: list[str], timeout: int = 8) -> str:
        try:
            r = subprocess.run(
                [docker, "exec", *args],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return ((r.stdout or "") + (r.stderr or ""))
        except (subprocess.TimeoutExpired, OSError):
            return ""

    def tcp_open(port: int, timeout: float = 1.5) -> bool:
        s = socket.socket()
        s.settimeout(timeout)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False
        finally:
            try:
                s.close()
            except OSError:
                pass

    def redis_ready() -> bool:
        if tcp_open(6380):
            return True
        out = dockerexec(["stinky-redis", "redis-cli", "ping"], timeout=3)
        if "PONG" in out.upper():
            return True
        try:
            lg = subprocess.run(
                [docker, "logs", "--tail", "20", "stinky-redis"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            blob = ((lg.stdout or "") + (lg.stderr or "")).lower()
            if "ready to accept connections" in blob:
                return True
        except (subprocess.TimeoutExpired, OSError):
            pass
        return False

    def reset_redis_transport() -> None:
        warn("resetting Redis transport dump (Postgres kept, ATLAS not touched)")
        subprocess.run([docker, "rm", "-f", "stinky-redis"], capture_output=True, timeout=30)
        for vol in ("project-genesis_redis-data", "genesis_redis-data"):
            subprocess.run([docker, "volume", "rm", "-f", vol], capture_output=True, timeout=30)
        subprocess.run(
            [
                docker,
                "compose",
                "-p",
                "project-genesis",
                "-f",
                str(ROOT / "docker-compose.yml"),
                "up",
                "-d",
                "redis",
            ],
            cwd=str(ROOT),
            capture_output=True,
            timeout=60,
        )

    pg_ok = False
    rd_ok = False
    say("  waiting for Postgres/Redis (will not hang)")
    for i in range(12):
        pg_out = dockerexec(["stinky-postgres", "pg_isready", "-U", "stinky", "-d", "stinky"], timeout=5)
        if "accepting" in pg_out:
            pg_ok = True
        rd_ok = redis_ready()
        if pg_ok and rd_ok:
            break
        say("  wait %s/12  postgres=%s redis=%s" % (i + 1, "ok" if pg_ok else "…", "ok" if rd_ok else "…"))
        time.sleep(2)
    if pg_ok and not rd_ok:
        reset_redis_transport()
        for i in range(12):
            rd_ok = redis_ready()
            if rd_ok:
                break
            say("  redis after reset %s/12" % (i + 1))
            time.sleep(2)
    if pg_ok:
        HEALTH["DATABASE"] = "CONNECTED"
        ok("Postgres ready (host 5433)")
    else:
        HEALTH["DATABASE"] = "DOWN"
        fail("DATABASE", "DOWN", "pg_isready did not report accepting connections", next_step="Wait for Docker, then retry from VS Code.")
    if rd_ok:
        HEALTH["REDIS"] = "CONNECTED"
        ok("Redis PONG (host 6380)")
        # Stop the hourly RDB fork that OOMs the 512m cap around T+3600.
        dockerexec(["stinky-redis", "redis-cli", "CONFIG", "SET", "save", ""], timeout=5)
        dockerexec(["stinky-redis", "redis-cli", "CONFIG", "SET", "maxmemory", "384mb"], timeout=5)
        dockerexec(["stinky-redis", "redis-cli", "XTRIM", "stinky.events", "MAXLEN", "~", "20000"], timeout=8)
        for i in range(8):
            info = dockerexec(["stinky-redis", "redis-cli", "INFO", "persistence"], timeout=4)
            if "loading:1" not in info.lower():
                break
            say("  redis still LOADING dump %s/8" % (i + 1))
            time.sleep(2)
    else:
        HEALTH["REDIS"] = "DOWN"
        try:
            lg = subprocess.run(
                [docker, "logs", "--tail", "30", "stinky-redis"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            raw = ((lg.stdout or "") + (lg.stderr or "")).strip().replace("\n", " | ")
            if raw:
                say("  redis logs: " + raw[:400])
        except (subprocess.TimeoutExpired, OSError):
            pass
        fail("REDIS", "DOWN", "redis-cli ping did not return PONG", next_step="Wait for Docker, then retry from VS Code.")
    log_line("postgres", HEALTH["DATABASE"], command="pg_isready -U stinky -d stinky")
    log_line("redis", HEALTH["REDIS"], command="redis-cli ping")


def apply_schema() -> None:
    step("[schema] apply SQL migrations (fail-soft)")
    if not DOCKER:
        return
    files = sorted(
        p for p in (ROOT / "services").rglob("*.sql") if "migrations" in p.parts
    )
    for f in files:
        say("  " + f.name)
        try:
            raw = f.read_text(encoding="utf-8-sig", errors="replace")
            subprocess.run(
                [DOCKER, "exec", "-i", "stinky-postgres", "psql", "-U", "stinky", "-d", "stinky", "-v", "ON_ERROR_STOP=0"],
                input=raw.encode("utf-8"),
                capture_output=True,
                timeout=60,
            )
        except Exception as exc:
            warn("%s skipped: %s" % (f.name, exc))
    ok("schema applied")
    log_line("schema", "ok")


def persistence_smoke() -> None:
    step("[persist] harmless smoke row (genesis_launcher_smoke)")
    if not DOCKER:
        return
    sql = (
        "CREATE TABLE IF NOT EXISTS genesis_launcher_smoke (\n"
        "  k text primary key,\n"
        "  v text,\n"
        "  at timestamptz default now()\n"
        ");\n"
        "INSERT INTO genesis_launcher_smoke(k, v) VALUES ('launcher', 'ok')\n"
        "  ON CONFLICT (k) DO UPDATE SET v = 'ok', at = now();\n"
        "SELECT v FROM genesis_launcher_smoke WHERE k = 'launcher';\n"
    )
    r = subprocess.run(
        [DOCKER, "exec", "-i", "stinky-postgres", "psql", "-U", "stinky", "-d", "stinky", "-v", "ON_ERROR_STOP=0", "-t", "-A"],
        input=sql,
        text=True,
        capture_output=True,
        timeout=20,
    )
    raw = (r.stdout or "") + (r.stderr or "")
    if "ok" in raw:
        ok("wrote and read launcher smoke row")
        log_line("persist", "ok", reason="write+read genesis_launcher_smoke")
    else:
        warn("persistence smoke did not confirm (not fatal)")
        log_line("persist", "UNKNOWN", reason="smoke row not confirmed")


def start_detached(name: str, port: int = 0, required: bool = False) -> int:
    if port > 0:
        owner = listen_pid(port)
        if owner > 0:
            if port == 3000:
                healthy = http_ok("http://127.0.0.1:3000/operator", 2)
            else:
                healthy = http_ok("http://127.0.0.1:%d/health" % port, 2)
            if healthy:
                ok("%-12s ALREADY RUNNING  pid %s  port %s" % (name, owner, port))
                log_line(name, "ALREADY RUNNING", pid_value=str(owner))
                HEALTH[name] = "ALREADY RUNNING"
                return owner
            reason = "port %d in use by pid %d (not Genesis-owned). Not killed (ATLAS isolation)." % (port, owner)
            if required:
                fail(name, "DOWN", reason, str(LOG_DIR / (name + ".log")), "Free the port or stop the other stack, then retry.")
            else:
                warn("%-12s skipped: %s" % (name, reason))
                log_line(name, "skipped", reason=reason)
            return 0
    existing = pid_from_log(name)
    if existing > 0 and pid_alive(existing):
        ok("%-12s ALREADY RUNNING  pid %s" % (name, existing))
        log_line(name, "ALREADY RUNNING", pid_value=str(existing))
        HEALTH[name] = "ALREADY RUNNING"
        return existing
    log = LOG_DIR / (name + ".log")
    try:
        if log.is_file():
            log.replace(Path(str(log) + ".old"))
    except OSError:
        pass
    try:
        log.write_text("", encoding="ascii")
    except OSError:
        pass
    starter = ROOT / "scripts" / "start-genesis-svc.cmd"
    if not starter.is_file():
        reason = "missing scripts\\start-genesis-svc.cmd"
        if required:
            fail(name, "DOWN", reason, str(log), "Pull origin/main and retry.")
        else:
            warn("%-12s %s" % (name, reason))
        return 0
    # Hidden pythonw + CREATE_BREAKAWAY_FROM_JOB so Explorer cannot kill children
    # and no extra consoles appear. scripts\start-genesis-svc.cmd (cmd START /B)
    # is the watchdog path only.
    runner = ROOT / "scripts" / "run_genesis_service.py"
    pyw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    pye = ROOT / ".venv" / "Scripts" / "python.exe"
    exe = str(pyw if pyw.is_file() else pye if pye.is_file() else sys.executable)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["STINKY_ROOT"] = str(ROOT)
    env["BROWSER"] = "none"
    flags = 0
    startupinfo = None
    if os.name == "nt":
        flags = 0x08000000 | 0x00000200 | 0x01000000  # CREATE_NO_WINDOW | NEW_PROCESS_GROUP | BREAKAWAY_FROM_JOB
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    proc = None
    try:
        logf = open(log, "a", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(
            [exe, str(runner), "--name", name],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=logf,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=flags,
            startupinfo=startupinfo,
        )
    except OSError:
        starter = ROOT / "scripts" / "start-genesis-svc.cmd"
        subprocess.run([str(CMD_EXE), "/d", "/c", str(starter), name], cwd=str(ROOT), timeout=15)
    pid = int(proc.pid) if proc is not None and proc.pid else 0
    if pid > 0:
        time.sleep(0.4)
        if proc is not None and proc.poll() is not None:
            pid = 0
        else:
            try:
                with log.open("a", encoding="utf-8", errors="replace") as f:
                    f.write("start pid=%s\n" % pid)
            except OSError:
                pass
            ok("%-12s PID %s" % (name, pid))
            log_line(name, "started", pid_value=str(pid), command="run_genesis_service.py --name " + name)
            HEALTH[name] = "STARTED"
            return pid
    time.sleep(0.8)
    pid = pid_from_log(name)
    if pid > 0:
        ok("%-12s PID %s" % (name, pid))
        log_line(name, "started", pid_value=str(pid), command="run_genesis_service.py --name " + name)
        HEALTH[name] = "STARTED"
        return pid
    reason = "process did not appear after start"
    if required:
        fail(name, "DOWN", reason, str(log), "Open the log and retry. Do not start a second copy.")
    else:
        warn("%-12s %s" % (name, reason))
        log_line(name, "DOWN", reason=reason)
        HEALTH[name] = "DOWN"
    return 0


def write_pid_file(procs: dict[str, int]) -> None:
    lines = ["%s=%s" % (k, v) for k, v in procs.items() if v and int(v) > 0]
    PID_FILE.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="ascii")


def show_health() -> None:
    say("")
    say("  %-22s %s" % ("COMPONENT", "STATUS"))
    say("  %-22s %s" % ("---------", "------"))
    for k, v in HEALTH.items():
        say("  %-22s %s" % (k, v))


def fill_operator(op) -> None:
    if not op:
        HEALTH.setdefault("OPERATOR", "NOT READY")
        HEALTH.setdefault("SYSTEM", "UNKNOWN")
        HEALTH.setdefault("LIVE MARKET DATA", "UNKNOWN")
        HEALTH.setdefault("LIVE GATE-1 EVENT", "UNKNOWN")
        HEALTH.setdefault("ACTIVE WATCHES", "UNKNOWN")
        return
    HEALTH["OPERATOR"] = "READY"
    if op.get("system_status"):
        HEALTH["SYSTEM"] = str(op["system_status"])
    db = op.get("database") or {}
    if db.get("status"):
        HEALTH["DATABASE"] = str(db["status"])
    if db.get("active_watch_count") is not None:
        HEALTH["ACTIVE WATCHES"] = str(db["active_watch_count"])
    HEALTH["LIVE MARKET DATA"] = str(op.get("live_data_status") or "UNKNOWN")
    if op.get("migration_watch_status"):
        HEALTH["SENTINEL"] = str(op["migration_watch_status"])
        HEALTH["MIGRATION WATCH"] = str(op["migration_watch_status"])
    gate = (op.get("gate_status") or {}).get("live_gate1")
    HEALTH["LIVE GATE-1 EVENT"] = str(gate) if gate else "UNKNOWN"
    discord = op.get("discord") or {}
    if discord.get("policy"):
        HEALTH["DISCORD POLICY"] = str(discord["policy"])
    if discord.get("delivery"):
        HEALTH["DISCORD DELIVERY"] = str(discord["delivery"])
    qs = (op.get("quality_state") or {}).get("current")
    if qs:
        HEALTH["QUALITY"] = str(qs)


def open_operator() -> None:
    try:
        webbrowser.open("http://127.0.0.1:3000/operator")
    except Exception as exc:
        warn("browser launch failed - Genesis itself continues running")
        log_line("browser", "failed", reason=str(exc))


def already_running() -> int:
    step("[duplicate] core already healthy")
    ok("ALREADY RUNNING - not starting another copy")
    HEALTH["BACKEND"] = "UP"
    HEALTH["FRONTEND"] = "UP"
    HEALTH["OPERATOR"] = "READY"
    fill_operator(get_json("http://127.0.0.1:8010/v1/operator"))
    if DOCKER:
        rd = subprocess.run(
            [DOCKER, "exec", "stinky-redis", "redis-cli", "ping"],
            capture_output=True,
            text=True,
        )
        HEALTH["REDIS"] = "CONNECTED" if "PONG" in ((rd.stdout or "") + (rd.stderr or "")) else "UNKNOWN"
    else:
        HEALTH["REDIS"] = "UNKNOWN"
    show_health()
    open_operator()
    log_line("launcher", "ALREADY RUNNING")
    say("")
    say("  ALREADY RUNNING. No duplicate processes started.")
    say("  Operator:  http://127.0.0.1:3000/operator")
    return 0


def main() -> int:
    global DOCKER, NPM
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--keep", action="store_true", help="do not stop a healthy instance")
    parser.add_argument("--restart", action="store_true", help="compat alias: stop then start (now the default)")
    parser.add_argument("--skip-install", action="store_true")
    args = parser.parse_args()

    configure_stdio()
    restore_search_path()
    os.chdir(ROOT)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DOCKER = find_docker()
    NPM = find_npm()

    say("")
    say("  GENESIS  intel-v1.11.0-operator")
    say("  " + str(ROOT))
    say("  python %s  cwd=%s" % (sys.version.split()[0], os.getcwd()))
    say("  Gate 1 = 33k USD / 5m  clamp 200k  (not a buy)")
    say("  Closing this window does NOT stop Genesis.")
    for n in ("git", "docker", "py", "python", "npm"):
        src = which_exe(n)
        if src:
            say("  %-8s %s" % (n, src))
        else:
            say("  %-8s NOT ON PATH" % n)
    say("")
    log_line("launcher", "begin", command="start_genesis.py", reason="py=%s root=%s" % (sys.version.split()[0], ROOT))

    if args.keep and not args.restart and core_healthy():
        return already_running()

    try:
        stop_owned_instance()
        sync_from_github(args.sync, args.skip_sync)
        ensure_dotenv()
        ensure_venv(args.skip_install)
        ensure_web()
        ensure_docker()
        if FAILED:
            raise RuntimeError("infrastructure failed")
        apply_schema()
        persistence_smoke()

        step("[services] start (detached; launcher exit does not kill them)")
        procs: dict[str, int] = {}
        procs["event-log"] = start_detached("event-log", port=8002, required=True)
        time.sleep(3)
        procs["api"] = start_detached("api", port=8010, required=True)
        time.sleep(2)
        procs["sentinel"] = start_detached("sentinel")
        time.sleep(1)
        procs["discord"] = start_detached("discord")
        time.sleep(1)
        procs["collector"] = start_detached("collector")
        time.sleep(1)
        procs["entities"] = start_detached("entities")
        time.sleep(1)
        procs["web"] = start_detached("web", port=3000, required=True)
        time.sleep(1)
        procs["maintain"] = start_detached("maintain")
        write_pid_file(procs)

        step("[health] real endpoints (not process-exists)")
        el_ok = wait_http("http://127.0.0.1:8002/health", 60, "event-log")
        api_ok = wait_http("http://127.0.0.1:8010/health", 60, "api")
        if api_ok:
            HEALTH["BACKEND"] = "UP"
            ok("BACKEND  http://127.0.0.1:8010/health")
        else:
            HEALTH["BACKEND"] = "DOWN"
            fail("BACKEND", "DOWN", "health endpoint did not respond", str(LOG_DIR / "api.log"), "See logs\\api.log and logs\\startup.log")
        if el_ok:
            ok("event-log http://127.0.0.1:8002/health")
        else:
            warn("event-log not ready - see logs\\event-log.log")

        web_ok = wait_http("http://127.0.0.1:3000/operator", 60, "operator")
        if web_ok:
            HEALTH["FRONTEND"] = "UP"
            ok("FRONTEND http://127.0.0.1:3000/operator")
        else:
            HEALTH["FRONTEND"] = "DOWN"
            fail(
                "FRONTEND",
                "DOWN",
                "operator page did not respond",
                str(LOG_DIR / "web.log"),
                "See logs\\web.log. Browser will not be opened.",
            )

        sent = int(procs.get("sentinel") or 0)
        if sent > 0 and pid_alive(sent):
            HEALTH["SENTINEL"] = "RUNNING"
            ok("SENTINEL process running (WS reachability is verified from the desk, not invented here)")
        else:
            HEALTH["SENTINEL"] = "DOWN"
            warn("SENTINEL process not running - see logs\\sentinel.log")

        op = get_json("http://127.0.0.1:8010/v1/operator") if api_ok else None
        fill_operator(op)
        HEALTH.setdefault("DATABASE", "UNKNOWN")
        HEALTH.setdefault("REDIS", "UNKNOWN")
        HEALTH.setdefault("SYSTEM", "UNKNOWN")
        HEALTH.setdefault("ACTIVE WATCHES", "UNKNOWN")
        show_health()
        log_line("health", "FAILED" if FAILED else "ok", reason=",".join("%s=%s" % (k, v) for k, v in HEALTH.items()))

        if web_ok:
            step("[ui] open operator desk (frontend is actually ready)")
            open_operator()
        else:
            warn("browser not opened because frontend is not ready")

        say("")
        if FAILED:
            say("  NOT READY. Services that started remain up. Fix the failed component.")
            say("  Log: " + str(STARTUP_LOG))
            return 1
        say("  READY. Services stay up after this window closes.")
        say("  Operator:  http://127.0.0.1:3000/operator")
        say("  Command:   http://127.0.0.1:3000/command-center")
        say("  Stop:      double-click  Stop Genesis  on the desktop")
        say("  LIVE GATE-1 is NOT OBSERVED until a real 33k USD / 5m print.")
        say("  Log: " + str(STARTUP_LOG))
        say("")
        log_line("launcher", "READY")
        return 0
    except Exception as exc:
        fail("launcher", "DOWN", str(exc), str(STARTUP_LOG), "Read the error above, then retry. Services already started were not killed.")
        show_health()
        return 1


if __name__ == "__main__":
    sys.exit(main())
