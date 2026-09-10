"""Fail-closed schema gate for the Windows Genesis launcher.

This gate runs before start_genesis.py. It starts only the existing Genesis Docker
infrastructure, applies every repository migration with PostgreSQL ON_ERROR_STOP,
and verifies the durable executor tables required by the current roadmap. It
never contacts Solana RPC, signs transactions, submits orders, or mutates wallets.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = "project-genesis"
REQUIRED_EXECUTOR_TABLES = (
    "executor_submission_state",
    "executor_submission_transition_audit",
)


def docker_bin() -> str:
    hit = shutil.which("docker") or shutil.which("docker.exe")
    if not hit:
        raise RuntimeError("docker.exe not found; cannot prove startup schema")
    return hit


def run(args: list[str], *, input_text: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(ROOT),
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )


def psql(docker: str, sql: str, *, stop_on_error: bool = True) -> subprocess.CompletedProcess[str]:
    return run(
        [
            docker, "exec", "-i", "stinky-postgres", "psql",
            "-U", "stinky", "-d", "stinky",
            "-v", "ON_ERROR_STOP=%s" % ("1" if stop_on_error else "0"),
            "-t", "-A",
        ],
        input_text=sql,
        timeout=90,
    )


def main() -> int:
    try:
        docker = docker_bin()
        compose = ROOT / "docker-compose.yml"
        if not compose.is_file():
            raise RuntimeError("docker-compose.yml missing")

        up = run([
            docker, "compose", "-p", PROJECT, "-f", str(compose),
            "--project-directory", str(ROOT), "up", "-d",
        ], timeout=150)
        if up.returncode != 0:
            raise RuntimeError("Genesis Docker startup failed: " + ((up.stderr or up.stdout or "")[-800:]))

        ready = False
        for _ in range(30):
            probe = run([docker, "exec", "stinky-postgres", "pg_isready", "-U", "stinky", "-d", "stinky"], timeout=8)
            if probe.returncode == 0 and "accepting connections" in (probe.stdout or ""):
                ready = True
                break
            time.sleep(2)
        if not ready:
            raise RuntimeError("PostgreSQL did not become ready for strict schema verification")

        migrations = sorted(p for p in (ROOT / "services").rglob("*.sql") if "migrations" in p.parts)
        if not migrations:
            raise RuntimeError("no SQL migrations discovered")
        for migration in migrations:
            sql = migration.read_text(encoding="utf-8-sig", errors="strict")
            result = psql(docker, sql, stop_on_error=True)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "")[-1200:]
                raise RuntimeError("migration failed: %s\n%s" % (migration.relative_to(ROOT), detail))

        names = ",".join("'%s'" % name for name in REQUIRED_EXECUTOR_TABLES)
        verify = psql(
            docker,
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN (%s) ORDER BY tablename;" % names,
        )
        if verify.returncode != 0:
            raise RuntimeError("executor schema verification query failed")
        observed = {line.strip() for line in (verify.stdout or "").splitlines() if line.strip()}
        missing = sorted(set(REQUIRED_EXECUTOR_TABLES) - observed)
        if missing:
            raise RuntimeError("required executor tables missing after migrations: " + ", ".join(missing))

        print("  STRICT SCHEMA GATE PASS: %d migrations; executor persistence verified" % len(migrations), flush=True)
        return 0
    except Exception as exc:
        print("", flush=True)
        print("GENESIS STARTUP BLOCKED BY STRICT SCHEMA GATE", flush=True)
        print("Reason: %s" % exc, flush=True)
        print("No Genesis application services were started by this gate.", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
