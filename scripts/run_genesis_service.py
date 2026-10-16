# Allowlisted Genesis service runner. Python, not PowerShell (Defender AMSI).
# Started by scripts\start-genesis-svc.cmd (cmd START /MIN).
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from contextlib import nullcontext
from functools import wraps
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
    "paper-intake-producer",
    "paper-runtime",
)

GENESIS_CONTAINERS = (
    "stinky-postgres",
    "stinky-redis",
    "stinky-minio",
    "stinky-minio-init",
)

LAUNCH_OBSERVATION = None  # Trusted in-process installation only; never env activated.

WATCH_CONTAINERS = (
    "stinky-postgres",
    "stinky-redis",
    "stinky-minio",
)

COOPERATIVE_SUPERVISOR = None  # Explicit trusted startup only; no environment activation.
COOPERATIVE_INSTALL_LOCK = threading.RLock()
COOPERATIVE_DELIVERY = None
COOPERATIVE_CHILDREN = None
MAINTENANCE_BINDING = None  # Explicit isolated installation only; never env activated.


def install_maintenance_binding(binding):
    global MAINTENANCE_BINDING
    from scripts.genesis_maintenance_binding import MaintenanceBinding
    with COOPERATIVE_INSTALL_LOCK:
        if MAINTENANCE_BINDING is not None or not isinstance(binding,MaintenanceBinding):
            raise RuntimeError('Explicit single maintenance binding required')
        binding.matches(LAUNCH_OBSERVATION,COOPERATIVE_SUPERVISOR)
        if binding.gate.jobs or binding.gate.loops or binding.manager.active or binding.manager.owners:
            raise RuntimeError('Maintenance binding must precede admission')
        MAINTENANCE_BINDING=binding


def install_cooperative_supervisor(gate):
    global COOPERATIVE_SUPERVISOR
    from scripts.genesis_supervisor_admission import SupervisorAdmission
    with COOPERATIVE_INSTALL_LOCK:
        if (COOPERATIVE_SUPERVISOR is not None or not isinstance(gate,SupervisorAdmission) or
            gate.owner['pid']!=os.getpid() or
            gate.owner['repository_sha256']!=hashlib.sha256(str(_SCRIPTS.parent).encode()).hexdigest()):
            raise RuntimeError('Cooperative supervisor requires exact native startup owner')
        gate.verify();COOPERATIVE_SUPERVISOR=gate


def supervisor_job(command):
    if MAINTENANCE_BINDING is not None:
        MAINTENANCE_BINDING.matches(LAUNCH_OBSERVATION,COOPERATIVE_SUPERVISOR)
        return MAINTENANCE_BINDING.work(command)
    return COOPERATIVE_SUPERVISOR.job(command) if COOPERATIVE_SUPERVISOR is not None else nullcontext()


def run_admitted_job(command, operation):
    with supervisor_job(command):return operation()


def supervisor_running():
    return COOPERATIVE_SUPERVISOR is None or not COOPERATIVE_SUPERVISOR.stop_event.is_set()


def supervisor_wait(seconds):
    if COOPERATIVE_SUPERVISOR is None:
        time.sleep(seconds)
    else:
        COOPERATIVE_SUPERVISOR.stop_event.wait(seconds)


def supervisor_loop(name):
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            gate=COOPERATIVE_SUPERVISOR
            with LAUNCH_OBSERVATION.loop(name) if LAUNCH_OBSERVATION is not None else nullcontext():
                with gate.loop(name) if gate is not None else nullcontext():
                    return function(*args, **kwargs)
        return run
    return decorate


def cooperative_status():
    gate=COOPERATIVE_SUPERVISOR
    if gate is None:return {'phase':'DISABLED','jobs':None,'identity_verified':None,'scope':'NO_INSTALLED_COOPERATIVE_SUPERVISOR'}
    with gate.changed:
        try:gate.verify();verified=True
        except Exception:gate.phase='HOLD';verified=False
        return {'phase':gate.phase,'jobs':len(gate.jobs) if verified else None,
                'identity_verified':verified,'scope':'JOB_TICKETS_ONLY_NOT_PROCESS_EXIT'}


def install_shutdown_delivery(authority, *, verify_controller, persist):
    global COOPERATIVE_DELIVERY
    from stinky_core.transport.shutdown_delivery import ShutdownReceiver
    gate = COOPERATIVE_SUPERVISOR
    with COOPERATIVE_INSTALL_LOCK:
        if gate is None or COOPERATIVE_DELIVERY is not None or gate.phase != 'RUNNING':
            raise RuntimeError('Authenticated clean supervisor delivery installation required')
        gate.verify()
        async def process(request, timeout):
            import asyncio
            ack = await asyncio.to_thread(gate.quiesce, request, timeout=timeout)
            if MAINTENANCE_BINDING is not None:
                ack['maintenance_boundary']=MAINTENANCE_BINDING.verify_drained()
            if COOPERATIVE_CHILDREN is None:
                # Ticket processing is deliberately not a process-exit certificate.
                return ack
            children = COOPERATIVE_CHILDREN.verify_exited()
            ack['verified_child_exit'] = True
            ack['child_exit_evidence'] = {'owners':children, 'journal_heads':dict(COOPERATIVE_CHILDREN.exit_heads)}
            return ack
        def hold():
            with gate.changed:
                gate.phase = 'HOLD'; gate.changed.notify_all()
        COOPERATIVE_DELIVERY = ShutdownReceiver(authority, manifest=gate.manifest,
            generation=lambda: gate.generation, verify_controller=verify_controller,
            process=process, persist=persist, hold=hold)


async def deliver_shutdown(envelope):
    if COOPERATIVE_DELIVERY is None:
        raise RuntimeError('Supervisor shutdown delivery disabled')
    return await COOPERATIVE_DELIVERY.receive(envelope)


def install_child_registry(registry):
    global COOPERATIVE_CHILDREN
    from scripts.genesis_child_exit import ChildRegistry
    with COOPERATIVE_INSTALL_LOCK:
        if (COOPERATIVE_SUPERVISOR is None or COOPERATIVE_CHILDREN is not None or
            not isinstance(registry, ChildRegistry) or registry.gate is not COOPERATIVE_SUPERVISOR or
            COOPERATIVE_SUPERVISOR.jobs):
            raise RuntimeError('Clean authenticated child registry required before dispatch')
        COOPERATIVE_CHILDREN = registry


def stopped_watch_containers(raw: str) -> list[str]:
    states: dict[str, str] = {}
    for line in raw.splitlines():
        name_part, separator, state_part = line.partition("|")
        if separator:
            states[name_part.strip()] = state_part.strip().lower()
    return [
        name
        for name in WATCH_CONTAINERS
        if states.get(name) and states[name] != "running"
    ]


def recover_watch_dependencies(root, docker, run):
    """Inactive-until-next-run ownership repair; no health/network restart fallback.

    Serialize with normal Start/Stop. The existing ownership gate verifies the
    project-genesis project/service labels. Verify ALL dependencies before any
    start, address containers by pinned ID and verify unchanged storage afterward.
    Successful start is not itself database/Redis/MinIO readiness certification.
    """
    from safe_genesis_start import startup_lock,validate_dependency
    def inspect():
        probe=run([docker,'inspect',*WATCH_CONTAINERS],timeout=20)
        if probe is None or probe.returncode!=0 or len(probe.stdout)>1024*1024:
            raise RuntimeError('Dependency inventory unavailable; no recovery attempted')
        records=json.loads(probe.stdout)
        if not isinstance(records,list) or len(records)!=3:
            raise RuntimeError('Complete dependency inventory required')
        by_name={r.get('Name'):r for r in records}
        if set(by_name)!={'/'+name for name in WATCH_CONTAINERS}:
            raise RuntimeError('Dependency identity set differs')
        result={}
        for name in WATCH_CONTAINERS:
            row=by_name['/'+name];state=validate_dependency(row,name)
            if (not re.fullmatch('[0-9a-f]{64}',row.get('Id','')) or
                not re.fullmatch('sha256:[0-9a-f]{64}',row.get('Image','')) or
                len(row.get('Mounts',[]))!=1 or row['Mounts'][0].get('RW') is not True):
                raise RuntimeError('Native dependency/storage identity unavailable')
            result[name]=(state,row)
        return result
    with startup_lock(Path(root)/'logs/application-start.lock'):
        before=inspect();stopped=[row['Id'] for state,row in before.values() if state!='running']
        if not stopped:return []
        outcome=run([docker,'start',*stopped],timeout=40)
        if outcome is None or outcome.returncode!=0:
            raise RuntimeError('Owned dependency start failed; no destructive fallback')
        after=inspect()
        for name,(state,row) in before.items():
            new_state,new=after[name]
            fields=('Id','Image','Name','Mounts','Config','HostConfig')
            if new_state!='running' or any(new.get(k)!=row.get(k) for k in fields):
                raise RuntimeError('Dependency start/storage preservation unverified')
        return stopped


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
    parser.add_argument("--protected-redis-grant", default=None)
    args = parser.parse_args()
    name = args.name
    if LAUNCH_OBSERVATION is not None:
        from scripts.genesis_supervisor_observation import SupervisorObservation
        if not isinstance(LAUNCH_OBSERVATION, SupervisorObservation) or (COOPERATIVE_SUPERVISOR is not None and MAINTENANCE_BINDING is None):
            raise RuntimeError('Explicit native supervisor observer required; HOLD')
        if MAINTENANCE_BINDING is not None:
            if name!='maintain':raise RuntimeError('Maintenance binding cannot authorize other services')
            MAINTENANCE_BINDING.matches(LAUNCH_OBSERVATION,COOPERATIVE_SUPERVISOR)
        LAUNCH_OBSERVATION.enter(name, os.getpid())
    if COOPERATIVE_SUPERVISOR is not None and COOPERATIVE_SUPERVISOR.owner['service']!=name:
        raise RuntimeError('Selected service contradicts cooperative supervisor owner')

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
    if args.protected_redis_grant is not None:
        if not args.protected_redis_grant:
            raise RuntimeError('Explicit protected Redis grant cannot be empty')
        if name not in ('event-log','api','sentinel','collector','entities'):
            raise RuntimeError('Protected Redis workload not certified for this service')
        env['GENESIS_PROTECTED_REDIS_GRANT']=args.protected_redis_grant

    def utc_stamp() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def append_log(message: str) -> None:
        return run_admitted_job(['maintenance-log'],lambda:append_log_unfenced(message)) if MAINTENANCE_BINDING is not None else append_log_unfenced(message)

    def append_log_unfenced(message: str) -> None:
        with log.open("a", encoding="utf-8", errors="replace") as f:
            f.write(message)
            if not message.endswith("\n"):
                f.write("\n")
            f.flush()

    supervisor_started_at = utc_stamp()
    stamp = "[" + supervisor_started_at + "] start pid=" + str(os.getpid())
    print("=== %s pid=%s" % (name, os.getpid()), flush=True)
    append_log(stamp)

    def write_supervisor_ownership_state(
        phase: str,
        *,
        services: dict[str, str] | None = None,
    ) -> None:
        """Persist supervisor identity immediately; never wait on unrelated HTTP health."""
        service_map = dict(services or {})
        payload = {
            "as_of": utc_stamp(),
            "system": phase if phase else system_state(service_map),
            "services": service_map,
            "watch": list(WATCH_CONTAINERS),
            "note": (
                "Supervisor ownership heartbeat. Service/app health is separate; "
                "UNKNOWN is not UP. Gate 1 is not here."
            ),
            "service": name,
            "supervisor_pid": os.getpid(),
            "supervisor_started_at": supervisor_started_at,
            "supervisor_launch_token": os.environ.get("GENESIS_SUPERVISOR_LAUNCH_TOKEN"),
            "supervisor_phase": phase or "RUNNING",
        }
        if LAUNCH_OBSERVATION is not None:
            payload = LAUNCH_OBSERVATION.heartbeat(payload)
        try:
            if MAINTENANCE_BINDING is not None:
                run_admitted_job(['maintenance-ownership-file'],lambda:write_state(log_dir / ("runtime-state-" + name + ".json"), payload))
            else:write_state(log_dir / ("runtime-state-" + name + ".json"), payload)
        except OSError:
            pass

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
        if COOPERATIVE_SUPERVISOR is not None and COOPERATIVE_SUPERVISOR.phase!='RUNNING':
            raise RuntimeError('Cooperative child state unresolved; no watchdog termination')
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

    def run_unfenced(
        cmd: list[str],
        cwd: Path | None = None,
        health_url: str | None = None,
    ) -> int:
        if COOPERATIVE_SUPERVISOR is not None and COOPERATIVE_CHILDREN is None:
            COOPERATIVE_SUPERVISOR.phase = 'HOLD'
            raise RuntimeError('Native child ownership must be installed before spawning')
        flags = 0
        startupinfo = None
        if os.name == "nt":
            flags = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        observed_cmd = LAUNCH_OBSERVATION.child_command(cmd) if LAUNCH_OBSERVATION is not None else cmd
        private_child_pipe = LAUNCH_OBSERVATION is not None and LAUNCH_OBSERVATION.private_pipe
        proc = subprocess.Popen(
            observed_cmd,
            cwd=str(cwd or root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE if private_child_pipe else subprocess.DEVNULL,
            text=True,
            creationflags=flags,
            startupinfo=startupinfo,
        )
        if MAINTENANCE_BINDING is not None:
            # Capture native ownership before the private handshake releases work.
            try:COOPERATIVE_CHILDREN.register(proc, observed_cmd)
            except BaseException:
                # Reject the still-private bootstrap by closing our exact pipe;
                # never signal an unverified child or release application dispatch.
                if proc.stdin is not None:proc.stdin.close()
                raise
        if LAUNCH_OBSERVATION is not None:
            LAUNCH_OBSERVATION.child_started(proc, observed_cmd)
        if COOPERATIVE_SUPERVISOR is not None:
            if COOPERATIVE_CHILDREN is None:
                raise RuntimeError('Cooperative supervisor child ownership unavailable; HOLD')
            if MAINTENANCE_BINDING is None:COOPERATIVE_CHILDREN.register(proc, cmd)
        assert proc.stdout is not None
        writer_ticket=MAINTENANCE_BINDING.ticket() if MAINTENANCE_BINDING is not None else None

        def pump_output() -> None:
            with MAINTENANCE_BINDING.writer(writer_ticket) if MAINTENANCE_BINDING is not None else nullcontext():
                pump_output_admitted()

        def pump_output_admitted() -> None:
            try:
                with log.open("a", encoding="utf-8", errors="replace") as f:
                    for line in proc.stdout:
                        sys.stdout.write(line)
                        sys.stdout.flush()
                        f.write(line)
                        f.flush()
            except (OSError, ValueError):
                if MAINTENANCE_BINDING is not None:MAINTENANCE_BINDING.hold()
                pass

        reader = threading.Thread(target=pump_output, name="%s-log-pump" % name, daemon=True)
        reader.start()

        if not health_url:
            # No application-level health endpoint exists for this worker. Poll
            # the child only so the supervisor can prove its own liveness; this
            # heartbeat is not an assertion that the application is healthy.
            last_heartbeat = 0.0
            while proc.poll() is None:
                now = time.monotonic()
                if now - last_heartbeat >= 60:
                    dump_runtime("SUPERVISING")
                    last_heartbeat = now
                time.sleep(API_HEALTH_POLL_SECONDS)
            code = int(proc.wait())
            if COOPERATIVE_CHILDREN is not None:
                COOPERATIVE_CHILDREN.verify_exited(proc)
            reader.join(timeout=3)
            if MAINTENANCE_BINDING is not None and reader.is_alive():MAINTENANCE_BINDING.hold()
            return code

        started = time.monotonic()
        seen_healthy = False
        unhealthy_since: float | None = None
        last_heartbeat = 0.0
        while proc.poll() is None:
            now = time.monotonic()
            healthy = http_ok(health_url, 2.5)
            if healthy:
                if not seen_healthy:
                    append_log("[%s] %s health watchdog armed pid=%s" % (utc_stamp(), name, proc.pid))
                seen_healthy = True
                unhealthy_since = None
                if now - last_heartbeat >= 60:
                    dump_runtime("RUNNING")
                    last_heartbeat = now
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
        if COOPERATIVE_CHILDREN is not None:
            COOPERATIVE_CHILDREN.verify_exited(proc)
        reader.join(timeout=3)
        if MAINTENANCE_BINDING is not None and reader.is_alive():MAINTENANCE_BINDING.hold()
        return code

    def run(cmd, cwd=None, health_url=None):
        return run_admitted_job(cmd,lambda:run_unfenced(cmd,cwd,health_url))

    def core_url(svc_name: str) -> str | None:
        for n, _port, url in CORE_HEALTH:
            if n == svc_name:
                return url
        return None

    @supervisor_loop('supervised-child-loop')
    def run_supervised(cmd: list[str], cwd: Path | None = None) -> int:
        """Restart on crash or sustained API health loss with a cap. Never storm."""
        delay = 5
        last = 0
        history: list[float] = []
        healthy_url = core_url(name)
        # All core HTTP services must recycle a child that remains alive while its
        # listener is unavailable. Process-exists is not service health.
        watched_url = healthy_url
        while supervisor_running():
            last = run(cmd, cwd, health_url=watched_url)
            if not supervisor_running():
                return last
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
            supervisor_wait(delay)
            delay = min(delay * 2, 60)
        return last

    def run_job_with_retry(cmd: list[str], attempts: int = 3) -> int:
        delay = 15
        last = 1
        for i in range(1, attempts + 1):
            if not supervisor_running():
                return last
            try:
                with supervisor_job(cmd) if MAINTENANCE_BINDING is not None else nullcontext():
                    with LAUNCH_OBSERVATION.job(cmd) if LAUNCH_OBSERVATION is not None else nullcontext():
                        last = run(cmd)
            except Exception as exc:
                from scripts.genesis_supervisor_admission import FencedAdmission
                if MAINTENANCE_BINDING is not None and isinstance(exc,FencedAdmission) and not supervisor_running():return last
                raise
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
                supervisor_wait(delay)
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
            # Aggregate current-health snapshot remains convenient for the operator,
            # but it is intentionally overwriteable by the maintain loop.
            if MAINTENANCE_BINDING is not None:
                run_admitted_job(['maintenance-health-file'],lambda:write_state(log_dir / "runtime-state.json", payload))
            else:write_state(log_dir / "runtime-state.json", payload)
        except OSError:
            pass
        # Preserve each supervisor's last durable ownership/phase independently.
        write_supervisor_ownership_state(phase or "RUNNING", services=core)

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

    def hidden_run(
        cmd: list[str], timeout: int = 40
    ) -> subprocess.CompletedProcess[str] | None:
        flags = 0
        startupinfo = None
        if os.name == "nt":
            flags = 0x08000000
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        try:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=flags,
                startupinfo=startupinfo,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None

    def watchdog_unfenced() -> None:
        """Exact-owned recovery only, serialized with Start/Stop. Never ATLAS."""
        docker = find_docker_bin()
        if not docker:
            return
        try:
            recover_watch_dependencies(root,docker,hidden_run)
        except (RuntimeError,OSError,ValueError,TypeError,KeyError):
            append_log('[%s] dependency watchdog blocked: ownership, lock or engine unverified; no destructive fallback' % utc_stamp())

    def watchdog_tick():
        return run_admitted_job(['dependency-watchdog'],watchdog_unfenced)

    # Ownership must be provable immediately, before any unrelated core HTTP
    # probes can consume the paper starter's bounded proof window.
    write_supervisor_ownership_state("SUPERVISING")

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
            code = run_supervised([py, "-m", "event_log.cli"])
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
        elif name == "paper-intake-producer":
            code = run_supervised([py, "-m", "stinky_api.prospective_paper_policy_runtime"])
        elif name == "paper-runtime":
            code = run_supervised([py, "-m", "stinky_api.paper_runtime_worker"])
        elif name == "maintain":
            # Slow six-hour maintenance must never starve the one-minute prospective
            # capture cadence. Keep it isolated in a daemon thread; research capture
            # remains PAPER/evidence-only in this supervisor's main loop.
            @supervisor_loop('slow-maintenance')
            def slow_maintenance_loop() -> None:
                while supervisor_running():
                    try:
                        run_job_with_retry([py, "-m", "post_migration.cli", "learn-success"])
                        run_job_with_retry([py, "-m", "post_migration.cli", "recompute-performance"])
                    except Exception as exc:
                        if MAINTENANCE_BINDING is not None and not supervisor_running():break
                        msg = "[%s] slow maintenance error %s\n" % (utc_stamp(), str(exc)[:200])
                        sys.stdout.write(msg)
                        sys.stdout.flush()
                        append_log(msg)
                    supervisor_wait(21600)

            slow_thread = threading.Thread(
                target=slow_maintenance_loop,
                name="genesis-slow-maintenance",
                daemon=True,
            )
            slow_thread.start()

            # V2 has a frozen 30-second pre-entry admission deadline. Keep its
            # prospective PAPER/evidence capture independent of the slower
            # one-minute research loop so scheduler phase cannot systematically
            # miss otherwise eligible decisions.
            from genesis_pass_provenance import Recorder, observe_pass
            pass_recorder = Recorder(log_dir / "v2-pass-provenance.jsonl")

            @supervisor_loop('v2-maintenance')
            def intelligence_execution_v2_loop() -> None:
                while supervisor_running():
                    try:
                        def capture_v2_pass():return observe_pass(
                            lambda: run_job_with_retry(
                                [py, str(root / "scripts" / "run_intelligence_execution_v2.py")],
                                attempts=1,
                            ),
                            pass_recorder,
                        )
                        if MAINTENANCE_BINDING is not None:
                            run_admitted_job(['maintenance-v2-pass-record'],capture_v2_pass)
                        else:capture_v2_pass()
                    except Exception as exc:
                        if MAINTENANCE_BINDING is not None and not supervisor_running():break
                        msg = "[%s] intelligence V2 capture error %s\n" % (
                            utc_stamp(),
                            str(exc)[:200],
                        )
                        sys.stdout.write(msg)
                        sys.stdout.flush()
                        append_log(msg)
                    supervisor_wait(10)

            v2_thread = threading.Thread(
                target=intelligence_execution_v2_loop,
                name="genesis-intelligence-execution-v2",
                daemon=True,
            )
            v2_thread.start()

            @supervisor_loop('research-maintenance')
            def research_maintenance_loop():
                while supervisor_running():
                    try:
                        watchdog_tick()
                        dump_runtime()
                    except Exception as exc:
                        if MAINTENANCE_BINDING is not None and not supervisor_running():break
                        msg = "[%s] watchdog error %s\n" % (utc_stamp(), str(exc)[:200])
                        sys.stdout.write(msg)
                        sys.stdout.flush()
                        append_log(msg)
                    # Prospective intelligence research capture. PAPER/evidence only:
                    # score eligible T+60 tracks, then classify only tracks that are
                    # still incomplete. The fixed boundary prevents historical backfill.
                    research_boundary = "2026-10-05T12:46:27.418241+00:00"
                    run_job_with_retry(
                        [py, str(root / "scripts" / "run_intelligence_shadow_scorer.py"),
                         "--boundary", research_boundary, "--limit", "500"], attempts=1
                    )
                    run_job_with_retry(
                        [py, str(root / "scripts" / "run_intelligence_paper_decisions.py"),
                         "--boundary", research_boundary, "--limit", "500"], attempts=1
                    )
                    # Prospective paper execution starts at a later, frozen boundary so
                    # the already-observed V3 evaluation cohort cannot tune its policy.
                    execution_boundary = "2026-10-07T07:09:02.404079+00:00"
                    run_job_with_retry(
                        [py, str(root / "scripts" / "run_intelligence_paper_execution_plans.py"),
                         "--boundary", execution_boundary, "--limit", "500"], attempts=1
                    )
                    # V2 prospective capture runs independently at a faster cadence above.
                    # Keep this research/V1 loop at its existing one-minute cadence.
                    supervisor_wait(60)
            research_maintenance_loop()
    finally:
        if MAINTENANCE_BINDING is None or supervisor_running():
            append_log("[%s] exit LASTEXITCODE=%s" % (utc_stamp(), code))
    return code


if __name__ == "__main__":
    sys.exit(main())
