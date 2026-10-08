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
            return int(resp.status) == 200
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
    from scripts.safe_genesis_start import ensure_dependencies
    ensure_dependencies(sys.modules[__name__])


def apply_schema() -> None:
    # Ordinary recovery verifies schema only; migration is a separate reviewed operation.
    from scripts.safe_genesis_start import verify_schema
    verify_schema(sys.modules[__name__])


def start_detached(name: str, port: int = 0, required: bool = False) -> int:
    # scripts/start-genesis-svc.cmd is the supported runner entry; no cmd START fallback.
    # Hidden pythonw and CREATE_NO_WINDOW keep detached recovery outside Explorer job lifetime.
    from scripts.safe_genesis_start import recover_service
    return recover_service(sys.modules[__name__], name)


def write_pid_file(procs: dict[str, int]) -> None:
    # A core-only recovery must retain metadata for separately managed services.
    # These entries remain hints, never health/ownership proof.
    known = {}
    if PID_FILE.is_file():
        for line in PID_FILE.read_text(encoding="ascii", errors="replace").splitlines():
            match = re.fullmatch(r"([a-z-]+)=(\d+)", line.strip())
            if match:
                known[match.group(1)] = int(match.group(2))
    known.update(procs)
    lines = ["%s=%d" % (name, pid) for name, pid in known.items() if pid > 0]
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--skip-install", action="store_true")
    profile = parser.add_mutually_exclusive_group()
    profile.add_argument("--core-only", action="store_true", help="default: recover the seven collection/V2 core services only")
    profile.add_argument("--full", "--full-startup", dest="full", action="store_true", help="also recover the separate persistent paper services")
    args = parser.parse_args()
    configure_stdio()
    restore_search_path()
    from scripts.safe_genesis_start import recover
    return recover(sys.modules[__name__], args)


if __name__ == "__main__":
    raise SystemExit(main())
