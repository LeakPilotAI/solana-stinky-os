"""Certified full-Postgres backup/restore for Genesis evidence.

Default mode targets the canonical local Timescale container (stinky-postgres).
The verifier NEVER restores over the source database. It restores into a unique
temporary database, compares deterministic evidence manifests, and drops it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
API_SRC = ROOT / "services" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

from stinky_api.paper_evidence_json import content_sha256  # noqa: E402
from stinky_api.paper_policy_identity import validated_policy_identity  # noqa: E402

FORMAT_VERSION = 1
REQUIRED_TABLES = (
    "events",
    "market_snapshots",
    "market_inspections",
    "score_snapshots",
    "entity_launches",
    "entity_launch_outcome_labels",
    "developer_longitudinal_snapshots",
    "developer_correlation_snapshots",
    "market_outcome_observations",
    "market_path_patterns",
    "market_path_pattern_occurrences",
    "market_pattern_calibration_snapshots",
    "paper_intake_producer_state",
    "paper_prospective_candidate",
    "paper_policy_registry",
    "paper_policy_active",
    "paper_policy_activation_audit",
    "paper_runtime_intake",
    "paper_runtime_record",
)
_DB_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class BackupError(RuntimeError):
    pass


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_db_name(value: str) -> str:
    if not _DB_RE.fullmatch(value):
        raise BackupError("unsafe_database_name")
    return value


def _quoted_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class PgTools:
    def __init__(
        self,
        *,
        mode: str,
        user: str,
        container: str = "stinky-postgres",
        host: str = "127.0.0.1",
        port: int = 5432,
    ) -> None:
        self.mode = mode
        self.user = user
        self.container = container
        self.host = host
        self.port = int(port)
        if mode not in {"docker", "direct"}:
            raise BackupError("unsupported_mode")

    def _tool(self, tool: str, *, interactive: bool = False) -> list[str]:
        if self.mode == "docker":
            cmd = ["docker", "exec"]
            if interactive:
                cmd.append("-i")
            return [*cmd, self.container, tool]
        return [tool, "-h", self.host, "-p", str(self.port)]

    def run(
        self,
        cmd: list[str],
        *,
        stdin=None,
        stdout=None,
        capture: bool = False,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        merged = os.environ.copy()
        if env:
            merged.update(env)
        result = subprocess.run(
            cmd,
            stdin=stdin,
            stdout=stdout if stdout is not None else (subprocess.PIPE if capture else None),
            stderr=subprocess.PIPE,
            text=False,
            env=merged,
            check=False,
        )
        if result.returncode != 0:
            err = (result.stderr or b"").decode("utf-8", errors="replace")[-4000:]
            raise BackupError(f"command_failed:{cmd[0]}:{result.returncode}:{err}")
        return result

    def psql(self, database: str, sql: str) -> str:
        database = _safe_db_name(database)
        cmd = [
            *self._tool("psql"),
            "-U", self.user,
            "-d", database,
            "-X", "-A", "-t",
            "-v", "ON_ERROR_STOP=1",
            "-c", "SET TIME ZONE 'UTC'; " + sql,
        ]
        result = self.run(cmd, capture=True)
        return (result.stdout or b"").decode("utf-8", errors="strict").strip()

    def create_database(self, database: str) -> None:
        database = _safe_db_name(database)
        cmd = [*self._tool("createdb"), "-U", self.user, database]
        self.run(cmd)

    def drop_database(self, database: str) -> None:
        database = _safe_db_name(database)
        cmd = [*self._tool("dropdb"), "-U", self.user, "--if-exists", database]
        self.run(cmd)

    def dump(self, database: str, path: Path) -> None:
        database = _safe_db_name(database)
        cmd = [
            *self._tool("pg_dump"),
            "-U", self.user,
            "-d", database,
            "--format=custom",
            "--no-owner",
            "--no-privileges",
        ]
        with path.open("wb") as out:
            self.run(cmd, stdout=out)

    def restore(self, database: str, path: Path) -> None:
        database = _safe_db_name(database)
        cmd = [
            *self._tool("pg_restore", interactive=self.mode == "docker"),
            "-U", self.user,
            "-d", database,
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
        ]
        with path.open("rb") as source:
            self.run(cmd, stdin=source)

    def has_timescaledb(self, database: str) -> bool:
        return self.psql(
            database,
            "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='timescaledb');",
        ) == "t"


def _table_exists(pg: PgTools, database: str, table: str) -> bool:
    value = pg.psql(database, f"SELECT to_regclass('public.{table}') IS NOT NULL;")
    return value == "t"


def _primary_key_columns(pg: PgTools, database: str, table: str) -> list[str]:
    sql = f"""
    SELECT a.attname
    FROM pg_index i
    JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum, ord) ON TRUE
    JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum
    WHERE i.indrelid='public.{table}'::regclass AND i.indisprimary
    ORDER BY k.ord;
    """
    raw = pg.psql(database, sql)
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _json_rows(pg: PgTools, database: str, table: str, columns: str = "to_jsonb(t)") -> list[Any]:
    pk = _primary_key_columns(pg, database, table)
    if not pk:
        raise BackupError(f"required_table_without_primary_key:{table}")
    order = ",".join("t." + _quoted_ident(col) for col in pk)
    raw = pg.psql(
        database,
        f"SELECT ({columns})::text FROM public.{_quoted_ident(table)} t ORDER BY {order};",
    )
    if not raw:
        return []
    rows: list[Any] = []
    for line in raw.splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise BackupError(f"non_json_manifest_row:{table}") from exc
    return rows


def _rows_sha256(rows: list[Any]) -> str:
    h = hashlib.sha256()
    for row in rows:
        encoded = json.dumps(
            row, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        h.update(encoded)
        h.update(b"\n")
    return h.hexdigest()


def _active_policy(pg: PgTools, database: str) -> dict[str, Any] | None:
    raw = pg.psql(
        database,
        """
        SELECT jsonb_build_object(
          'policy_version',r.policy_version,
          'policy_sha256',r.policy_sha256,
          'provenance',r.policy_payload->'provenance',
          'activated_at',a.activated_at
        )::text
        FROM paper_policy_active a
        JOIN paper_policy_registry r ON r.policy_version=a.policy_version
        WHERE a.singleton=TRUE
        LIMIT 1;
        """,
    )
    return json.loads(raw) if raw else None


def _integrity_report(pg: PgTools, database: str) -> dict[str, Any]:
    errors: list[str] = []
    counts = {
        "paper_policy_registry": 0,
        "paper_prospective_candidate": 0,
        "paper_runtime_intake": 0,
        "paper_runtime_record": 0,
    }

    policies = _json_rows(
        pg, database, "paper_policy_registry",
        "jsonb_build_object('policy_version',t.policy_version,'policy_sha256',t.policy_sha256,'policy_payload',t.policy_payload)",
    )
    counts["paper_policy_registry"] = len(policies)
    for row in policies:
        payload = row.get("policy_payload")
        version = row.get("policy_version")
        sha = row.get("policy_sha256")
        try:
            if not isinstance(payload, dict) or content_sha256(payload) != sha:
                errors.append(f"policy_payload_hash:{version}")
                continue
            identity = {
                "policy_version": version,
                "policy_sha256": sha,
                "provenance": payload.get("provenance"),
            }
            if validated_policy_identity(identity) is None:
                errors.append(f"policy_identity:{version}")
        except (TypeError, ValueError, OverflowError, RecursionError):
            errors.append(f"policy_payload_noncanonical:{version}")

    candidates = _json_rows(
        pg, database, "paper_prospective_candidate",
        "jsonb_build_object('candidate_id',t.candidate_id,'t0_evidence',t.t0_evidence,'t0_evidence_sha256',t.t0_evidence_sha256,'frozen_bundle',t.frozen_bundle,'frozen_bundle_sha256',t.frozen_bundle_sha256)",
    )
    counts["paper_prospective_candidate"] = len(candidates)
    for row in candidates:
        candidate_id = str(row.get("candidate_id"))
        try:
            if content_sha256(row.get("t0_evidence")) != row.get("t0_evidence_sha256"):
                errors.append(f"t0_hash:{candidate_id}")
            frozen = row.get("frozen_bundle")
            frozen_sha = row.get("frozen_bundle_sha256")
            if frozen is None:
                if frozen_sha is not None:
                    errors.append(f"frozen_null_hash:{candidate_id}")
            elif content_sha256(frozen) != frozen_sha:
                errors.append(f"frozen_bundle_hash:{candidate_id}")
        except (TypeError, ValueError, OverflowError, RecursionError):
            errors.append(f"candidate_noncanonical:{candidate_id}")

    intakes = _json_rows(
        pg, database, "paper_runtime_intake",
        "jsonb_build_object('intake_id',t.intake_id,'payload',t.payload,'payload_sha256',t.payload_sha256)",
    )
    counts["paper_runtime_intake"] = len(intakes)
    for row in intakes:
        intake_id = str(row.get("intake_id"))
        try:
            if content_sha256(row.get("payload")) != row.get("payload_sha256"):
                errors.append(f"intake_payload_hash:{intake_id}")
        except (TypeError, ValueError, OverflowError, RecursionError):
            errors.append(f"intake_noncanonical:{intake_id}")

    records = _json_rows(
        pg, database, "paper_runtime_record",
        "jsonb_build_object('intake_id',t.intake_id,'policy_version',t.policy_version,'policy_sha256',t.policy_sha256,'policy_evidence_backed',t.policy_evidence_backed,'record',t.record)",
    )
    counts["paper_runtime_record"] = len(records)
    for row in records:
        intake_id = str(row.get("intake_id"))
        record = row.get("record")
        identity = record.get("policy_identity") if isinstance(record, dict) else None
        if row.get("policy_version") is None and identity is None:
            continue
        if not isinstance(identity, dict) or validated_policy_identity(identity) is None:
            errors.append(f"runtime_policy_identity:{intake_id}")
            continue
        if (
            identity.get("policy_version") != row.get("policy_version")
            or identity.get("policy_sha256") != row.get("policy_sha256")
            or identity.get("provenance", {}).get("evidence_backed") is not row.get("policy_evidence_backed")
        ):
            errors.append(f"runtime_first_class_identity:{intake_id}")

    active = _active_policy(pg, database)
    if active is not None:
        identity = {
            "policy_version": active.get("policy_version"),
            "policy_sha256": active.get("policy_sha256"),
            "provenance": active.get("provenance"),
        }
        if validated_policy_identity(identity) is None:
            errors.append("active_policy_identity")

    return {
        "status": "PASS" if not errors else "FAIL",
        "counts": counts,
        "errors": sorted(errors),
    }


def build_manifest(pg: PgTools, database: str) -> dict[str, Any]:
    missing = [table for table in REQUIRED_TABLES if not _table_exists(pg, database, table)]
    if missing:
        raise BackupError("missing_required_tables:" + ",".join(missing))

    tables: dict[str, Any] = {}
    for table in REQUIRED_TABLES:
        rows = _json_rows(pg, database, table)
        tables[table] = {
            "row_count": len(rows),
            "rows_sha256": _rows_sha256(rows),
        }

    integrity = _integrity_report(pg, database)
    if integrity["status"] != "PASS":
        raise BackupError("source_integrity_failed:" + ",".join(integrity["errors"]))

    return {
        "format_version": FORMAT_VERSION,
        "required_tables": list(REQUIRED_TABLES),
        "tables": tables,
        "active_policy": _active_policy(pg, database),
        "integrity": integrity,
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def certify(
    pg: PgTools,
    *,
    database: str,
    output_dir: Path,
) -> dict[str, Any]:
    database = _safe_db_name(database)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dump_path = output_dir / f"genesis-{database}-{stamp}.dump"
    source_manifest_path = output_dir / f"genesis-{database}-{stamp}.source-manifest.json"
    restored_manifest_path = output_dir / f"genesis-{database}-{stamp}.restored-manifest.json"
    certification_path = output_dir / f"genesis-{database}-{stamp}.certification.json"
    restore_db = _safe_db_name(f"genesis_restore_{uuid.uuid4().hex[:12]}")

    source_manifest = build_manifest(pg, database)
    _write_json(source_manifest_path, source_manifest)
    pg.dump(database, dump_path)
    dump_sha = _sha_file(dump_path)

    restore_created = False
    restored_manifest: dict[str, Any] | None = None
    match = False
    restore_error: BaseException | None = None
    try:
        pg.create_database(restore_db)
        restore_created = True
        if pg.has_timescaledb(database):
            pg.psql(restore_db, "CREATE EXTENSION IF NOT EXISTS timescaledb;")
            pg.psql(restore_db, "SELECT timescaledb_pre_restore();")
        pg.restore(restore_db, dump_path)
        if pg.has_timescaledb(restore_db):
            pg.psql(restore_db, "SELECT timescaledb_post_restore();")
        restored_manifest = build_manifest(pg, restore_db)
        _write_json(restored_manifest_path, restored_manifest)
        match = source_manifest == restored_manifest
        if not match:
            raise BackupError("restored_manifest_mismatch")
    except BaseException as exc:
        restore_error = exc
    finally:
        if restore_created:
            try:
                pg.drop_database(restore_db)
            except BaseException as drop_exc:
                if restore_error is None:
                    restore_error = drop_exc
                else:
                    restore_error = BackupError(f"{restore_error};drop_failed:{drop_exc}")

    certification = {
        "status": "PASS" if restore_error is None and match else "FAIL",
        "format_version": FORMAT_VERSION,
        "certified_at": _utc_stamp(),
        "source_database": database,
        "temporary_restore_database": restore_db,
        "source_database_modified": False,
        "restored_over_source": False,
        "temporary_restore_dropped": restore_created and restore_error is None,
        "dump_file": str(dump_path),
        "dump_sha256": dump_sha,
        "source_manifest": str(source_manifest_path),
        "restored_manifest": str(restored_manifest_path),
        "manifest_match": match,
        "required_tables": list(REQUIRED_TABLES),
    }
    _write_json(certification_path, certification)
    if restore_error is not None:
        raise BackupError(str(restore_error))
    return certification


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Certify a Genesis Postgres backup via isolated restore.")
    parser.add_argument("command", choices=("certify",))
    parser.add_argument("--mode", choices=("docker", "direct"), default="docker")
    parser.add_argument("--container", default="stinky-postgres")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="stinky")
    parser.add_argument("--database", default="stinky")
    parser.add_argument("--output-dir", default=str(ROOT / "backups"))
    return parser


def main() -> int:
    args = _parser().parse_args()
    pg = PgTools(
        mode=args.mode,
        user=args.user,
        container=args.container,
        host=args.host,
        port=args.port,
    )
    try:
        result = certify(pg, database=args.database, output_dir=Path(args.output_dir))
    except (BackupError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({
            "status": "FAIL",
            "error": str(exc)[:2000],
            "source_database_modified": False,
            "restored_over_source": False,
        }, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
