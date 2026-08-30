"""SQLite persistence for IntelligenceMemory.

Postgres is the production contract (MEMORY_DDL). This store exists so
restart/hydration can be proven without a running Postgres. Schema is the
same facts. JSON is stored as TEXT. Timestamps as ISO text.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from stinky_core.memory import IntelligenceMemory

SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS wallet_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet TEXT NOT NULL,
    mint TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'early_buyer',
    sol_spent REAL,
    source TEXT NOT NULL DEFAULT 'observed',
    side TEXT DEFAULT 'buy',
    entry_price REAL,
    exit_size REAL,
    exit_price REAL,
    ret_pct REAL,
    UNIQUE (wallet, mint, role)
);
CREATE TABLE IF NOT EXISTS wallet_outcome_labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet TEXT NOT NULL,
    mint TEXT NOT NULL,
    labeled_at TEXT NOT NULL,
    label TEXT NOT NULL,
    label_version TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'outcome-v1.0.0',
    UNIQUE (wallet, mint)
);
CREATE TABLE IF NOT EXISTS creator_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator TEXT NOT NULL,
    mint TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    migrated INTEGER,
    source TEXT NOT NULL DEFAULT 'observed',
    UNIQUE (creator, mint)
);
CREATE TABLE IF NOT EXISTS creator_outcome_labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator TEXT NOT NULL,
    mint TEXT NOT NULL,
    labeled_at TEXT NOT NULL,
    label TEXT NOT NULL,
    label_version TEXT NOT NULL,
    UNIQUE (creator, mint)
);
CREATE TABLE IF NOT EXISTS wallet_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_a TEXT NOT NULL,
    wallet_b TEXT NOT NULL,
    kind TEXT NOT NULL,
    mint TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    confidence REAL,
    reason TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS pattern_fingerprints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    mint TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    features TEXT NOT NULL DEFAULT '{}',
    UNIQUE (fingerprint, mint)
);
CREATE TABLE IF NOT EXISTS pattern_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    mint TEXT NOT NULL,
    labeled_at TEXT NOT NULL,
    label TEXT NOT NULL,
    label_version TEXT NOT NULL,
    UNIQUE (fingerprint, mint)
);
CREATE TABLE IF NOT EXISTS intelligence_decisions (
    mint TEXT PRIMARY KEY,
    decision_timestamp TEXT NOT NULL,
    protocol TEXT,
    volume_m5_usd REAL,
    pipeline_status TEXT,
    has_intelligence INTEGER,
    promote INTEGER,
    stinky_score REAL,
    alert_ok INTEGER,
    alert_reason TEXT,
    synthetic_level TEXT,
    rug_level TEXT,
    outcome_label TEXT,
    label_version TEXT,
    model_version TEXT,
    row TEXT NOT NULL
);
"""


class SqliteMemoryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SQLITE_DDL)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for table in (
            "wallet_observations",
            "wallet_outcome_labels",
            "creator_observations",
            "creator_outcome_labels",
            "wallet_relationships",
            "pattern_fingerprints",
            "pattern_outcomes",
            "intelligence_decisions",
        ):
            out[table] = int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return out

    def persist(self, memory: IntelligenceMemory) -> dict[str, int]:
        snap = memory.snapshot_rows()
        before = self.counts()
        for r in snap["wallet_obs"]:
            self.conn.execute(
                """INSERT OR IGNORE INTO wallet_observations
                   (wallet, mint, observed_at, role, sol_spent, source, side, entry_price, exit_size, exit_price, ret_pct)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["wallet"], r["mint"], r["observed_at"], r["role"], r["sol_spent"], r["source"],
                 r.get("side") or "buy", r.get("entry_price"), r.get("exit_size"), r.get("exit_price"), r.get("ret_pct")),
            )
        for r in snap["wallet_outcomes"]:
            self.conn.execute(
                """INSERT OR IGNORE INTO wallet_outcome_labels
                   (wallet, mint, labeled_at, label, label_version, source)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (r["wallet"], r["mint"], r["labeled_at"], r["label"], r["label_version"], r.get("source") or r["label_version"]),
            )
        for r in snap["creator_obs"]:
            self.conn.execute(
                """INSERT OR IGNORE INTO creator_observations
                   (creator, mint, observed_at, migrated, source)
                   VALUES (?, ?, ?, ?, ?)""",
                (r["creator"], r["mint"], r["observed_at"], 1 if r.get("migrated") else 0, r["source"]),
            )
        for r in snap["creator_outcomes"]:
            self.conn.execute(
                """INSERT OR IGNORE INTO creator_outcome_labels
                   (creator, mint, labeled_at, label, label_version)
                   VALUES (?, ?, ?, ?, ?)""",
                (r["creator"], r["mint"], r["labeled_at"], r["label"], r["label_version"]),
            )
        for r in snap["fingerprints"]:
            self.conn.execute(
                """INSERT OR IGNORE INTO pattern_fingerprints
                   (fingerprint, mint, observed_at, features)
                   VALUES (?, ?, ?, ?)""",
                (r["fingerprint"], r["mint"], r["observed_at"], json.dumps(r.get("features") or {})),
            )
        for r in snap["fingerprint_outcomes"]:
            self.conn.execute(
                """INSERT OR IGNORE INTO pattern_outcomes
                   (fingerprint, mint, labeled_at, label, label_version)
                   VALUES (?, ?, ?, ?, ?)""",
                (r["fingerprint"], r["mint"], r["labeled_at"], r["label"], r["label_version"]),
            )
        for r in snap["relationships"]:
            self.conn.execute(
                """INSERT INTO wallet_relationships
                   (wallet_a, wallet_b, kind, mint, observed_at, confidence, reason, evidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["wallet_a"], r["wallet_b"], r["kind"], r["mint"], r["observed_at"],
                 r["confidence"], r["reason"], json.dumps(r.get("evidence") or {})),
            )
        self.conn.commit()
        after = self.counts()
        return {"before": before, "after": after}  # type: ignore[return-value]

    def load(self, memory: IntelligenceMemory | None = None) -> IntelligenceMemory:
        mem = memory if memory is not None else IntelligenceMemory()
        def rows(sql: str) -> list[dict[str, Any]]:
            return [dict(r) for r in self.conn.execute(sql).fetchall()]

        wobs = rows("SELECT wallet, mint, observed_at, role, sol_spent, source, side, entry_price, exit_size, exit_price, ret_pct FROM wallet_observations")
        mem.load_wallet_obs(wobs)
        mem.load_wallet_outcomes(rows("SELECT wallet AS subject, mint, labeled_at, label, label_version FROM wallet_outcome_labels"))
        mem.load_creator_obs(rows("SELECT creator AS wallet, mint, observed_at, source, migrated FROM creator_observations"))
        mem.load_creator_outcomes(rows("SELECT creator AS subject, mint, labeled_at, label, label_version FROM creator_outcome_labels"))
        fps = rows("SELECT fingerprint, mint, observed_at, features FROM pattern_fingerprints")
        for r in fps:
            if isinstance(r.get("features"), str):
                try:
                    r["features"] = json.loads(r["features"] or "{}")
                except json.JSONDecodeError:
                    r["features"] = {}
        mem.load_fingerprints(fps)
        mem.load_fingerprint_outcomes(rows("SELECT fingerprint AS subject, mint, labeled_at, label, label_version FROM pattern_outcomes"))
        return mem
