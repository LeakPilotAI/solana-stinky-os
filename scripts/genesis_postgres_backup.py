"""Certified full-Postgres backup/restore for Genesis evidence.

Default mode targets the canonical local Timescale container (stinky-postgres).
The verifier NEVER restores over the source database. It restores into a unique
temporary database, compares deterministic evidence manifests, and drops it.
"""
from __future__ import annotations

import argparse
import asyncio
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

import asyncpg  # noqa: E402

from stinky_api.paper_evidence_json import content_sha256  # noqa: E402
from stinky_api.paper_policy_identity import validated_policy_identity  # noqa: E402

FORMAT_VERSION = 2
STREAM_PROGRESS_ROWS = 100_000
METADATA_TIMEOUT_SECONDS = 60
BACKUP_COMMAND_TIMEOUT_SECONDS = 60 * 60
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
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


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
        password: str | None = None,
        network: str = "project-genesis_default",
        db_host: str = "postgres",
    ) -> None:
        self.mode = mode
        self.user = user
        self.container = container
        self.host = host
        self.port = int(port)
        self.password = password or os.environ.get("PGPASSWORD") or user
        self.network = network
        self.db_host = db_host
        if mode not in {"docker-network", "direct"}:
            raise BackupError("unsupported_mode")
        if not _SAFE_TOKEN_RE.fullmatch(network):
            raise BackupError("unsafe_network_name")
        if not _SAFE_TOKEN_RE.fullmatch(db_host):
            raise BackupError("unsafe_database_host")

    def run(
        self,
        cmd: list[str],
        *,
        stdin=None,
        stdout=None,
        capture: bool = False,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess:
        merged = os.environ.copy()
        if env:
            merged.update(env)
        try:
            result = subprocess.run(
                cmd,
                stdin=stdin,
                stdout=stdout if stdout is not None else (subprocess.PIPE if capture else None),
                stderr=subprocess.PIPE,
                text=False,
                env=merged,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise BackupError(f"command_timeout:{cmd[0]}:{timeout}") from exc
        if result.returncode != 0:
            err = (result.stderr or b"").decode("utf-8", errors="replace")[-4000:]
            raise BackupError(f"command_failed:{cmd[0]}:{result.returncode}:{err}")
        return result

    async def _connect(self, database: str):
        return await asyncpg.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=_safe_db_name(database),
            timeout=15,
            command_timeout=METADATA_TIMEOUT_SECONDS,
            server_settings={"timezone": "UTC"},
        )

    async def _fetch_text_direct(self, database: str, sql: str) -> str:
        conn = await self._connect(database)
        try:
            rows = await conn.fetch(sql)
            vals = []
            for row in rows:
                value = row[0] if len(row) else None
                if value is not None:
                    vals.append(str(value))
            return "\n".join(vals).strip()
        finally:
            await conn.close()

    def _docker_psql_cmd(self, database: str) -> list[str]:
        return [
            "docker", "run", "--rm", "-i",
            "--network", self.network,
            "-e", "PGPASSWORD",
            "postgres:16",
            "psql",
            "-h", self.db_host,
            "-p", str(self.port),
            "-U", self.user,
            "-d", _safe_db_name(database),
            "-X", "-A", "-t", "-q",
            "-v", "ON_ERROR_STOP=1",
        ]

    def psql(self, database: str, sql: str) -> str:
        if self.mode == "direct":
            try:
                return asyncio.run(self._fetch_text_direct(database, sql))
            except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
                raise BackupError(
                    f"database_query_failed:{database}:{type(exc).__name__}:{exc}"
                ) from exc
        result = self.run(
            [*self._docker_psql_cmd(database), "-c", sql],
            capture=True,
            env={"PGPASSWORD": self.password},
            timeout=METADATA_TIMEOUT_SECONDS,
        )
        return (result.stdout or b"").decode("utf-8", errors="strict").strip()

    async def _execute_direct(self, database: str, sql: str) -> None:
        conn = await self._connect(database)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    def _execute(self, database: str, sql: str) -> None:
        if self.mode == "direct":
            try:
                asyncio.run(self._execute_direct(database, sql))
                return
            except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
                raise BackupError(
                    f"database_execute_failed:{database}:{type(exc).__name__}:{exc}"
                ) from exc
        self.run(
            [*self._docker_psql_cmd(database), "-c", sql],
            env={"PGPASSWORD": self.password},
            timeout=METADATA_TIMEOUT_SECONDS,
        )

    def create_database(self, database: str) -> None:
        database = _safe_db_name(database)
        self._execute("postgres", f"CREATE DATABASE {_quoted_ident(database)}")

    def drop_database(self, database: str) -> None:
        database = _safe_db_name(database)
        self._execute(
            "postgres",
            f"DROP DATABASE IF EXISTS {_quoted_ident(database)} WITH (FORCE)",
        )

    def _client_tool(self, tool: str) -> list[str]:
        if self.mode == "direct":
            return [tool, "-h", self.host, "-p", str(self.port)]
        return [
            "docker", "run", "--rm", "-i",
            "--network", self.network,
            "-e", "PGPASSWORD",
            "postgres:16",
            tool,
            "-h", self.db_host,
            "-p", str(self.port),
        ]

    def dump(self, database: str, path: Path) -> None:
        database = _safe_db_name(database)
        cmd = [
            *self._client_tool("pg_dump"),
            "-U", self.user,
            "-d", database,
            "--format=custom",
            "--no-owner",
            "--no-privileges",
        ]
        with path.open("wb") as out:
            self.run(
                cmd,
                stdout=out,
                env={"PGPASSWORD": self.password},
                timeout=BACKUP_COMMAND_TIMEOUT_SECONDS,
            )

    def restore(self, database: str, path: Path) -> None:
        database = _safe_db_name(database)
        cmd = [
            *self._client_tool("pg_restore"),
            "-U", self.user,
            "-d", database,
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
        ]
        with path.open("rb") as source:
            self.run(
                cmd,
                stdin=source,
                env={"PGPASSWORD": self.password},
                timeout=BACKUP_COMMAND_TIMEOUT_SECONDS,
            )

    async def _stream_digest_direct(
        self, database: str, sql: str, label: str
    ) -> tuple[int, str]:
        conn = await self._connect(database)
        digest = hashlib.sha256()
        row_count = 0
        try:
            async with conn.transaction():
                async for row in conn.cursor(sql, prefetch=2000):
                    value = row[0] if len(row) else None
                    if value is None:
                        continue
                    digest.update(str(value).encode("utf-8"))
                    digest.update(b"\n")
                    row_count += 1
                    if row_count % STREAM_PROGRESS_ROWS == 0:
                        print(f"  [manifest] {label}: {row_count:,} rows hashed", flush=True)
        finally:
            await conn.close()
        return row_count, digest.hexdigest()

    def stream_digest(
        self,
        database: str,
        sql: str,
        *,
        label: str,
        count_sql: str,
    ) -> tuple[int, str]:
        if self.mode == "direct":
            try:
                return asyncio.run(self._stream_digest_direct(database, sql, label))
            except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
                raise BackupError(
                    f"stream_query_failed:{label}:{type(exc).__name__}:{exc}"
                ) from exc

        shell = (
            'set -eu; '
            'count="$(psql -h "$GENESIS_DB_HOST" -p "$GENESIS_DB_PORT" '
            '-U "$GENESIS_DB_USER" -d "$GENESIS_DB_NAME" -X -A -t -q '
            '-v ON_ERROR_STOP=1 -c "$GENESIS_COUNT_SQL")"; '
            'digest="$(psql -h "$GENESIS_DB_HOST" -p "$GENESIS_DB_PORT" '
            '-U "$GENESIS_DB_USER" -d "$GENESIS_DB_NAME" -X -A -t -q '
            '-v ON_ERROR_STOP=1 -c "$GENESIS_HASH_SQL" | sha256sum | cut -d" " -f1)"; '
            'printf "%s\t%s\n" "$count" "$digest"'
        )
        cmd = [
            "docker", "run", "--rm",
            "--network", self.network,
            "-e", "PGPASSWORD",
            "-e", f"GENESIS_DB_HOST={self.db_host}",
            "-e", f"GENESIS_DB_PORT={self.port}",
            "-e", f"GENESIS_DB_USER={self.user}",
            "-e", f"GENESIS_DB_NAME={_safe_db_name(database)}",
            "-e", f"GENESIS_COUNT_SQL={count_sql}",
            "-e", f"GENESIS_HASH_SQL={sql}",
            "postgres:16",
            "sh", "-c", shell,
        ]
        result = self.run(
            cmd,
            capture=True,
            env={"PGPASSWORD": self.password},
            timeout=BACKUP_COMMAND_TIMEOUT_SECONDS,
        )
        raw = (result.stdout or b"").decode("utf-8", errors="strict").strip()
        try:
            count_raw, digest = raw.split("\t", 1)
            row_count = int(count_raw.strip())
        except (ValueError, TypeError) as exc:
            raise BackupError(f"invalid_stream_digest_result:{label}:{raw[:200]}") from exc
        digest = digest.strip()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise BackupError(f"invalid_stream_digest_sha256:{label}")
        return row_count, digest

    def has_extension(self, database: str, extension: str) -> bool:
        if not re.fullmatch(r"[A-Za-z0-9_]+", extension):
            raise BackupError("unsafe_extension_name")
        value = self.psql(
            database,
            f"SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='{extension}');",
        )
        return value.lower() in {"t", "true", "1"}

    def has_timescaledb(self, database: str) -> bool:
        return self.has_extension(database, "timescaledb")

def _table_exists(pg: PgTools, database: str, table: str) -> bool:
    value = pg.psql(database, f"SELECT to_regclass('public.{table}') IS NOT NULL;")
    return value.lower() in {"t", "true", "1"}


def _table_columns(pg: PgTools, database: str, table: str) -> set[str]:
    raw = pg.psql(
        database,
        f"""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name='{table}'
        ORDER BY ordinal_position;
        """,
    )
    return {line.strip() for line in raw.splitlines() if line.strip()}


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


def _table_digest(pg: PgTools, database: str, table: str) -> dict[str, Any]:
    pk = _primary_key_columns(pg, database, table)
    if not pk:
        raise BackupError(f"required_table_without_primary_key:{table}")
    order = ",".join("t." + _quoted_ident(col) for col in pk)
    if pg.has_extension(database, "pgcrypto"):
        projection = (
            "encode(digest(convert_to((to_jsonb(t))::text,'UTF8'),'sha256'),'hex')"
        )
        hash_mode = "ordered_row_sha256_v1"
    else:
        projection = "(to_jsonb(t))::text"
        hash_mode = "ordered_raw_json_v1"
    label = f"{database}.{table}"
    print(f"  [manifest] {label}: hashing...", flush=True)
    row_count, rows_sha256 = pg.stream_digest(
        database,
        f"SELECT {projection} FROM public.{_quoted_ident(table)} t ORDER BY {order};",
        label=label,
        count_sql=f"SELECT COUNT(*) FROM public.{_quoted_ident(table)};",
    )
    print(
        f"  [manifest] {label}: done ({row_count:,} rows, {rows_sha256[:16]}...)",
        flush=True,
    )
    return {
        "row_count": row_count,
        "rows_sha256": rows_sha256,
        "hash_mode": hash_mode,
    }


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

    runtime_columns = _table_columns(pg, database, "paper_runtime_record")
    first_class_columns = {
        "policy_version",
        "policy_sha256",
        "policy_evidence_backed",
    }
    if first_class_columns.issubset(runtime_columns):
        runtime_identity_schema = "first_class"
        runtime_projection = (
            "jsonb_build_object("
            "'intake_id',t.intake_id,"
            "'policy_version',t.policy_version,"
            "'policy_sha256',t.policy_sha256,"
            "'policy_evidence_backed',t.policy_evidence_backed,"
            "'record',t.record)"
        )
    elif first_class_columns.isdisjoint(runtime_columns):
        runtime_identity_schema = "legacy_embedded_only"
        runtime_projection = (
            "jsonb_build_object("
            "'intake_id',t.intake_id,"
            "'record',t.record)"
        )
    else:
        missing = sorted(first_class_columns - runtime_columns)
        errors.append("runtime_policy_identity_partial_schema:" + ",".join(missing))
        runtime_identity_schema = "partial_invalid"
        runtime_projection = (
            "jsonb_build_object("
            "'intake_id',t.intake_id,"
            "'record',t.record)"
        )

    records = _json_rows(
        pg,
        database,
        "paper_runtime_record",
        runtime_projection,
    )
    counts["paper_runtime_record"] = len(records)
    for row in records:
        intake_id = str(row.get("intake_id"))
        record = row.get("record")
        identity = record.get("policy_identity") if isinstance(record, dict) else None

        if runtime_identity_schema == "legacy_embedded_only":
            # Pre-013 databases legitimately have no first-class policy columns.
            # Never infer historical identity from the current active policy.
            # If a legacy record already embeds identity, it must still validate.
            if identity is not None:
                if not isinstance(identity, dict) or validated_policy_identity(identity) is None:
                    errors.append(f"runtime_policy_identity:{intake_id}")
            continue

        if runtime_identity_schema != "first_class":
            continue
        if row.get("policy_version") is None and identity is None:
            continue
        if not isinstance(identity, dict) or validated_policy_identity(identity) is None:
            errors.append(f"runtime_policy_identity:{intake_id}")
            continue
        if (
            identity.get("policy_version") != row.get("policy_version")
            or identity.get("policy_sha256") != row.get("policy_sha256")
            or identity.get("provenance", {}).get("evidence_backed")
            is not row.get("policy_evidence_backed")
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
        "runtime_policy_identity_schema": runtime_identity_schema,
        "errors": sorted(errors),
    }


def build_manifest(pg: PgTools, database: str) -> dict[str, Any]:
    missing = [table for table in REQUIRED_TABLES if not _table_exists(pg, database, table)]
    if missing:
        raise BackupError("missing_required_tables:" + ",".join(missing))

    tables: dict[str, Any] = {}
    for table in REQUIRED_TABLES:
        tables[table] = _table_digest(pg, database, table)

    print(f"[backup] {database}: validating semantic evidence hashes...", flush=True)
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

    print(f"[backup] {database}: building source evidence manifest...", flush=True)
    source_manifest = build_manifest(pg, database)
    _write_json(source_manifest_path, source_manifest)
    print(f"[backup] {database}: source manifest written", flush=True)
    print(f"[backup] {database}: creating full pg_dump...", flush=True)
    pg.dump(database, dump_path)
    dump_sha = _sha_file(dump_path)
    print(
        f"[backup] {database}: dump complete ({dump_path.stat().st_size:,} bytes, {dump_sha[:16]}...)",
        flush=True,
    )

    restore_created = False
    restored_manifest: dict[str, Any] | None = None
    match = False
    restore_error: BaseException | None = None
    try:
        print(f"[backup] creating isolated restore database {restore_db}...", flush=True)
        pg.create_database(restore_db)
        restore_created = True
        if pg.has_timescaledb(database):
            pg.psql(restore_db, "CREATE EXTENSION IF NOT EXISTS timescaledb;")
            pg.psql(restore_db, "SELECT timescaledb_pre_restore();")
        print(f"[backup] restoring dump into {restore_db}...", flush=True)
        pg.restore(restore_db, dump_path)
        print(f"[backup] restore complete; validating restored evidence...", flush=True)
        if pg.has_timescaledb(restore_db):
            pg.psql(restore_db, "SELECT timescaledb_post_restore();")
        restored_manifest = build_manifest(pg, restore_db)
        _write_json(restored_manifest_path, restored_manifest)
        match = source_manifest == restored_manifest
        print(f"[backup] source/restored manifest match: {match}", flush=True)
        if not match:
            raise BackupError("restored_manifest_mismatch")
    except BaseException as exc:
        restore_error = exc
    finally:
        if restore_created:
            try:
                print(f"[backup] dropping isolated restore database {restore_db}...", flush=True)
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
    parser.add_argument("--mode", choices=("docker-network", "direct"), default="docker-network")
    parser.add_argument("--container", default="stinky-postgres")
    parser.add_argument("--network", default="project-genesis_default")
    parser.add_argument("--db-host", default="postgres")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="stinky")
    parser.add_argument("--password", default=None)
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
        password=args.password,
        network=args.network,
        db_host=args.db_host,
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
