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
CREATE TABLE IF NOT EXISTS market_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mint TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    volume_m5_usd REAL,
    price_usd REAL,
    liquidity_usd REAL,
    source TEXT NOT NULL DEFAULT 'observed',
    market_cap_usd REAL,
    buys INTEGER,
    sells INTEGER,
    txns INTEGER,
    unique_buyers INTEGER,
    unique_sellers INTEGER,
    volume_since_gate REAL
);
CREATE TABLE IF NOT EXISTS intelligence_investigations (
    mint TEXT PRIMARY KEY,
    gate1_at TEXT NOT NULL,
    discovered_at TEXT,
    protocol TEXT,
    volume_5m_at_gate REAL,
    liquidity_at_gate REAL,
    market_cap_at_gate REAL,
    price_at_gate REAL,
    pair_identifier TEXT,
    creator TEXT,
    gate_decision TEXT,
    investigation_status TEXT,
    correlation_id TEXT,
    row TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quality_state_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mint TEXT NOT NULL,
    as_of TEXT NOT NULL,
    state TEXT NOT NULL,
    previous_state TEXT,
    severity TEXT,
    row TEXT NOT NULL
);
"""


class SqliteMemoryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SQLITE_DDL)
        for alt in (
            "ALTER TABLE market_observations ADD COLUMN market_cap_usd REAL",
            "ALTER TABLE market_observations ADD COLUMN buys INTEGER",
            "ALTER TABLE market_observations ADD COLUMN sells INTEGER",
            "ALTER TABLE market_observations ADD COLUMN txns INTEGER",
            "ALTER TABLE market_observations ADD COLUMN unique_buyers INTEGER",
            "ALTER TABLE market_observations ADD COLUMN unique_sellers INTEGER",
            "ALTER TABLE market_observations ADD COLUMN volume_since_gate REAL",
        ):
            try:
                self.conn.execute(alt)
            except sqlite3.OperationalError:
                pass
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
            "market_observations",
            "intelligence_investigations",
            "quality_state_transitions",
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
        for r in snap.get("decisions") or []:
            nested = r.get("row") if isinstance(r.get("row"), dict) else {k: v for k, v in r.items() if k != "row"}
            self.conn.execute(
                """INSERT OR REPLACE INTO intelligence_decisions
                   (mint, decision_timestamp, protocol, volume_m5_usd, pipeline_status,
                    has_intelligence, promote, stinky_score, alert_ok, alert_reason,
                    synthetic_level, rug_level, outcome_label, label_version, model_version, row)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    r.get("mint"),
                    r.get("decision_timestamp"),
                    r.get("protocol"),
                    r.get("volume_m5_usd"),
                    r.get("pipeline_status"),
                    1 if r.get("has_intelligence") else 0,
                    1 if r.get("promote") else 0,
                    r.get("stinky_score"),
                    1 if r.get("alert_ok") else 0,
                    r.get("alert_reason"),
                    r.get("synthetic_level"),
                    r.get("rug_level"),
                    r.get("outcome_label"),
                    r.get("label_version"),
                    r.get("model_version"),
                    json.dumps(nested, default=str),
                ),
            )
        for r in snap.get("market_ticks") or []:
            self.conn.execute(
                """INSERT INTO market_observations
                   (mint, observed_at, volume_m5_usd, price_usd, liquidity_usd, source,
                    market_cap_usd, buys, sells, txns, unique_buyers, unique_sellers, volume_since_gate)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["mint"], r["observed_at"], r.get("volume_m5_usd"), r.get("price_usd"),
                 r.get("liquidity_usd"), r.get("source") or "observed",
                 r.get("market_cap_usd"), r.get("buys"), r.get("sells"), r.get("txns"),
                 r.get("unique_buyers"), r.get("unique_sellers"), r.get("volume_since_gate")),
            )
        for r in snap.get("investigations") or []:
            nested = dict(r)
            self.conn.execute(
                """INSERT OR IGNORE INTO intelligence_investigations
                   (mint, gate1_at, discovered_at, protocol, volume_5m_at_gate, liquidity_at_gate,
                    market_cap_at_gate, price_at_gate, pair_identifier, creator, gate_decision,
                    investigation_status, correlation_id, row)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    r.get("mint"),
                    r.get("gate1_at") or r.get("decision_timestamp") or "",
                    r.get("discovered_at"),
                    r.get("protocol"),
                    r.get("volume_5m_at_gate"),
                    r.get("liquidity_at_gate"),
                    r.get("market_cap_at_gate"),
                    r.get("price_at_gate"),
                    r.get("pair_identifier"),
                    r.get("creator"),
                    r.get("gate_decision"),
                    r.get("investigation_status"),
                    r.get("correlation_id"),
                    json.dumps(nested, default=str),
                ),
            )
        for r in snap.get("quality_states") or []:
            nested = dict(r)
            self.conn.execute(
                """INSERT INTO quality_state_transitions
                   (mint, as_of, state, previous_state, severity, row)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    r.get("mint"),
                    r.get("as_of") or "",
                    r.get("state"),
                    r.get("previous_state"),
                    r.get("severity"),
                    json.dumps(nested, default=str),
                ),
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
        decs = rows("SELECT mint, decision_timestamp, protocol, volume_m5_usd, pipeline_status, has_intelligence, promote, stinky_score, alert_ok, alert_reason, synthetic_level, rug_level, outcome_label, label_version, model_version, row FROM intelligence_decisions")
        for r in decs:
            if isinstance(r.get("row"), str):
                try:
                    r["row"] = json.loads(r["row"] or "{}")
                except json.JSONDecodeError:
                    r["row"] = {}
            r["has_intelligence"] = bool(r.get("has_intelligence"))
            r["promote"] = bool(r.get("promote"))
            r["alert_ok"] = bool(r.get("alert_ok"))
        mem.load_decisions(decs)
        ticks = rows("SELECT mint, observed_at, volume_m5_usd, price_usd, liquidity_usd, source, market_cap_usd, buys, sells, txns, unique_buyers, unique_sellers, volume_since_gate FROM market_observations")
        mem.load_market_ticks(ticks)
        try:
            invs = rows("SELECT mint, gate1_at, discovered_at, protocol, volume_5m_at_gate, liquidity_at_gate, market_cap_at_gate, price_at_gate, pair_identifier, creator, gate_decision, investigation_status, correlation_id, row FROM intelligence_investigations")
            for r in invs:
                if isinstance(r.get("row"), str):
                    try:
                        r["row"] = json.loads(r["row"] or "{}")
                    except json.JSONDecodeError:
                        r["row"] = {}
            mem.load_investigations(invs)
        except sqlite3.OperationalError:
            pass
        try:
            qs = rows("SELECT mint, as_of, state, previous_state, severity, row FROM quality_state_transitions")
            for r in qs:
                if isinstance(r.get("row"), str):
                    try:
                        r["row"] = json.loads(r["row"] or "{}")
                    except json.JSONDecodeError:
                        r["row"] = {}
            mem.load_quality_states(qs)
        except sqlite3.OperationalError:
            pass
        return mem
