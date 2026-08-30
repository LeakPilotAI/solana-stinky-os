"""As-of-correct accumulating intelligence memory.

Collect once. Preserve. Query only what was known before a decision timestamp.
Future outcomes, future wallet stats, and future entity links cannot leak.

This is an in-process store. SQL DDL is the persistence contract for Postgres.
Never fabricates wallets, fees, identities, or similarity.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from stinky_core.pools import is_rankable_wallet

MEMORY_VERSION = "memory-v1.2.0-remember"

MEMORY_DDL = """
CREATE TABLE IF NOT EXISTS wallet_observations (
    id BIGSERIAL PRIMARY KEY,
    wallet TEXT NOT NULL,
    mint TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    role TEXT NOT NULL DEFAULT 'early_buyer',
    sol_spent DOUBLE PRECISION,
    source TEXT NOT NULL DEFAULT 'observed',
    UNIQUE (wallet, mint, role)
);
CREATE INDEX IF NOT EXISTS idx_wallet_obs_wallet_time ON wallet_observations (wallet, observed_at);
CREATE INDEX IF NOT EXISTS idx_wallet_obs_mint ON wallet_observations (mint);

CREATE TABLE IF NOT EXISTS wallet_outcome_labels (
    id BIGSERIAL PRIMARY KEY,
    wallet TEXT NOT NULL,
    mint TEXT NOT NULL,
    labeled_at TIMESTAMPTZ NOT NULL,
    label TEXT NOT NULL,
    label_version TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'outcome-v1.0.0',
    UNIQUE (wallet, mint)
);
CREATE INDEX IF NOT EXISTS idx_wallet_out_wallet_time ON wallet_outcome_labels (wallet, labeled_at);

CREATE TABLE IF NOT EXISTS creator_observations (
    id BIGSERIAL PRIMARY KEY,
    creator TEXT NOT NULL,
    mint TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    migrated BOOLEAN,
    source TEXT NOT NULL DEFAULT 'observed',
    UNIQUE (creator, mint)
);
CREATE INDEX IF NOT EXISTS idx_creator_obs_creator_time ON creator_observations (creator, observed_at);

CREATE TABLE IF NOT EXISTS creator_outcome_labels (
    id BIGSERIAL PRIMARY KEY,
    creator TEXT NOT NULL,
    mint TEXT NOT NULL,
    labeled_at TIMESTAMPTZ NOT NULL,
    label TEXT NOT NULL,
    label_version TEXT NOT NULL,
    UNIQUE (creator, mint)
);

CREATE TABLE IF NOT EXISTS wallet_relationships (
    id BIGSERIAL PRIMARY KEY,
    wallet_a TEXT NOT NULL,
    wallet_b TEXT NOT NULL,
    kind TEXT NOT NULL,
    mint TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    confidence DOUBLE PRECISION,
    reason TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_rel_a ON wallet_relationships (wallet_a, observed_at);
CREATE INDEX IF NOT EXISTS idx_rel_b ON wallet_relationships (wallet_b, observed_at);

CREATE TABLE IF NOT EXISTS pattern_fingerprints (
    id BIGSERIAL PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    mint TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    features JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (fingerprint, mint)
);
CREATE INDEX IF NOT EXISTS idx_fp_key_time ON pattern_fingerprints (fingerprint, observed_at);

CREATE TABLE IF NOT EXISTS pattern_outcomes (
    id BIGSERIAL PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    mint TEXT NOT NULL,
    labeled_at TIMESTAMPTZ NOT NULL,
    label TEXT NOT NULL,
    label_version TEXT NOT NULL,
    UNIQUE (fingerprint, mint)
);

CREATE TABLE IF NOT EXISTS intelligence_decisions (
    mint TEXT PRIMARY KEY,
    decision_timestamp TIMESTAMPTZ NOT NULL,
    protocol TEXT,
    volume_m5_usd DOUBLE PRECISION,
    pipeline_status TEXT,
    has_intelligence BOOLEAN,
    promote BOOLEAN,
    stinky_score DOUBLE PRECISION,
    alert_ok BOOLEAN,
    alert_reason TEXT,
    synthetic_level TEXT,
    rug_level TEXT,
    outcome_label TEXT,
    label_version TEXT,
    model_version TEXT,
    row JSONB NOT NULL
);
"""
# Extra columns for existing Postgres installs (007). CREATE TABLE IF NOT EXISTS
# above will not add them to an already-created table.
MEMORY_ALTERS = (
    "ALTER TABLE wallet_observations ADD COLUMN IF NOT EXISTS side TEXT DEFAULT 'buy'",
    "ALTER TABLE wallet_observations ADD COLUMN IF NOT EXISTS entry_price DOUBLE PRECISION",
    "ALTER TABLE wallet_observations ADD COLUMN IF NOT EXISTS exit_size DOUBLE PRECISION",
    "ALTER TABLE wallet_observations ADD COLUMN IF NOT EXISTS exit_price DOUBLE PRECISION",
    "ALTER TABLE wallet_observations ADD COLUMN IF NOT EXISTS ret_pct DOUBLE PRECISION",
)
MEMORY_INDEXES: tuple[str, ...] = ()

MEMORY_INSERT_WALLET_OBS = """
INSERT INTO wallet_observations (wallet, mint, observed_at, role, sol_spent, source)
VALUES (:wallet, :mint, :observed_at, :role, :sol_spent, :source)
ON CONFLICT (wallet, mint, role) DO NOTHING
"""
MEMORY_INSERT_WALLET_OUTCOME = """
INSERT INTO wallet_outcome_labels (wallet, mint, labeled_at, label, label_version, source)
VALUES (:wallet, :mint, :labeled_at, :label, :label_version, :source)
ON CONFLICT (wallet, mint) DO NOTHING
"""
MEMORY_INSERT_CREATOR_OBS = """
INSERT INTO creator_observations (creator, mint, observed_at, migrated, source)
VALUES (:creator, :mint, :observed_at, :migrated, :source)
ON CONFLICT (creator, mint) DO NOTHING
"""
MEMORY_INSERT_CREATOR_OUTCOME = """
INSERT INTO creator_outcome_labels (creator, mint, labeled_at, label, label_version)
VALUES (:creator, :mint, :labeled_at, :label, :label_version)
ON CONFLICT (creator, mint) DO NOTHING
"""
MEMORY_INSERT_FINGERPRINT = """
INSERT INTO pattern_fingerprints (fingerprint, mint, observed_at, features)
VALUES (:fingerprint, :mint, :observed_at, CAST(:features AS jsonb))
ON CONFLICT (fingerprint, mint) DO NOTHING
"""
MEMORY_INSERT_FINGERPRINT_OUTCOME = """
INSERT INTO pattern_outcomes (fingerprint, mint, labeled_at, label, label_version)
VALUES (:fingerprint, :mint, :labeled_at, :label, :label_version)
ON CONFLICT (fingerprint, mint) DO NOTHING
"""
MEMORY_INSERT_RELATIONSHIP = """
INSERT INTO wallet_relationships (wallet_a, wallet_b, kind, mint, observed_at, confidence, reason, evidence)
VALUES (:wallet_a, :wallet_b, :kind, :mint, :observed_at, :confidence, :reason, CAST(:evidence AS jsonb))
"""
MEMORY_SELECT_WALLET_OBS = "SELECT wallet, mint, observed_at, role, sol_spent, source FROM wallet_observations"
MEMORY_SELECT_WALLET_OUTCOME = "SELECT wallet AS subject, mint, labeled_at, label, label_version FROM wallet_outcome_labels"
MEMORY_SELECT_CREATOR_OBS = "SELECT creator AS wallet, mint, observed_at, 'creator' AS role, NULL AS sol_spent, source FROM creator_observations"
MEMORY_SELECT_CREATOR_OUTCOME = "SELECT creator AS subject, mint, labeled_at, label, label_version FROM creator_outcome_labels"
MEMORY_SELECT_FINGERPRINT = "SELECT fingerprint, mint, observed_at, features FROM pattern_fingerprints"
MEMORY_SELECT_FINGERPRINT_OUTCOME = "SELECT fingerprint AS subject, mint, labeled_at, label, label_version FROM pattern_outcomes"
MEMORY_SELECT_RELATIONSHIP = "SELECT wallet_a, wallet_b, kind, mint, observed_at, confidence, reason, evidence FROM wallet_relationships"


def _parse_ts(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(float(v), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(v).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _before(ts: datetime | None, as_of: datetime | None) -> bool:
    """True if ts is strictly before as_of. Missing as_of → include all known."""
    if ts is None:
        return False
    if as_of is None:
        return True
    return ts < as_of


def _maybe_float(v: Any) -> float | None:
    if v is None or v is True or v is False:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


@dataclass
class WalletObservation:
    wallet: str
    mint: str
    observed_at: datetime
    role: str = "early_buyer"
    sol_spent: float | None = None
    source: str = "observed"
    side: str = "buy"
    entry_price: float | None = None
    exit_size: float | None = None
    exit_price: float | None = None
    ret_pct: float | None = None


@dataclass
class OutcomeLabel:
    subject: str
    mint: str
    labeled_at: datetime
    label: str
    label_version: str = "outcome-v1.0.0"


@dataclass
class RelationshipEdge:
    wallet_a: str
    wallet_b: str
    kind: str
    mint: str
    observed_at: datetime
    confidence: float
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class FingerprintRecord:
    fingerprint: str
    mint: str
    observed_at: datetime
    features: dict[str, Any] = field(default_factory=dict)


class IntelligenceMemory:
    """Accumulating store. All queries are as-of-decision unless as_of is None."""

    def __init__(self) -> None:
        self.wallet_obs: list[WalletObservation] = []
        self.wallet_outcomes: list[OutcomeLabel] = []
        self.creator_obs: list[WalletObservation] = []  # role=creator
        self.creator_outcomes: list[OutcomeLabel] = []
        self.relationships: list[RelationshipEdge] = []
        self.fingerprints: list[FingerprintRecord] = []
        self.fingerprint_outcomes: list[OutcomeLabel] = []
        self.version = MEMORY_VERSION

    def record_wallet(
        self,
        *,
        wallet: str,
        mint: str,
        observed_at: Any,
        role: str = "early_buyer",
        sol_spent: float | None = None,
        source: str = "observed",
        side: str = "buy",
        entry_price: float | None = None,
        exit_size: float | None = None,
        exit_price: float | None = None,
        ret_pct: float | None = None,
    ) -> bool:
        ts = _parse_ts(observed_at)
        w = (wallet or "").strip()
        m = (mint or "").strip()
        if not ts or not w or not m or not is_rankable_wallet(w):
            return False
        key = (w, m, role)
        for existing in self.wallet_obs:
            if (existing.wallet, existing.mint, existing.role) == key:
                return False
        self.wallet_obs.append(
            WalletObservation(
                wallet=w, mint=m, observed_at=ts, role=role, sol_spent=sol_spent, source=source,
                side=side or "buy", entry_price=entry_price, exit_size=exit_size,
                exit_price=exit_price, ret_pct=ret_pct,
            )
        )
        return True

    def record_creator(
        self,
        *,
        creator: str,
        mint: str,
        observed_at: Any,
        migrated: bool | None = True,
    ) -> bool:
        ts = _parse_ts(observed_at)
        c = (creator or "").strip()
        m = (mint or "").strip()
        if not ts or not c or not m:
            return False
        for existing in self.creator_obs:
            if existing.wallet == c and existing.mint == m:
                return False
        self.creator_obs.append(
            WalletObservation(
                wallet=c, mint=m, observed_at=ts, role="creator",
                sol_spent=None, source="observed" if migrated else "observed_unmigrated",
            )
        )
        return True

    def record_relationship(
        self,
        *,
        wallet_a: str,
        wallet_b: str,
        kind: str,
        mint: str,
        observed_at: Any,
        confidence: float,
        reason: str,
        evidence: dict[str, Any] | None = None,
    ) -> bool:
        ts = _parse_ts(observed_at)
        a, b = sorted(((wallet_a or "").strip(), (wallet_b or "").strip()))
        if not ts or not a or not b or a == b:
            return False
        if not is_rankable_wallet(a) or not is_rankable_wallet(b):
            return False
        self.relationships.append(
            RelationshipEdge(
                wallet_a=a, wallet_b=b, kind=kind, mint=(mint or "").strip(),
                observed_at=ts, confidence=float(confidence), reason=reason,
                evidence=dict(evidence or {}),
            )
        )
        return True

    def record_fingerprint(
        self,
        *,
        fingerprint: str,
        mint: str,
        observed_at: Any,
        features: dict[str, Any] | None = None,
    ) -> bool:
        ts = _parse_ts(observed_at)
        fp = (fingerprint or "").strip()
        m = (mint or "").strip()
        if not ts or not fp or not m:
            return False
        for existing in self.fingerprints:
            if existing.fingerprint == fp and existing.mint == m:
                return False
        self.fingerprints.append(
            FingerprintRecord(fingerprint=fp, mint=m, observed_at=ts, features=dict(features or {}))
        )
        return True

    def record_outcome(
        self,
        *,
        mint: str,
        labeled_at: Any,
        label: str,
        wallets: Iterable[str] | None = None,
        creator: str | None = None,
        fingerprint: str | None = None,
        label_version: str = "outcome-v1.0.0",
    ) -> None:
        ts = _parse_ts(labeled_at)
        m = (mint or "").strip()
        lab = (label or "UNKNOWN").upper()
        if not ts or not m:
            return
        for w in wallets or []:
            w = (w or "").strip()
            if not w or not is_rankable_wallet(w):
                continue
            if any(o.subject == w and o.mint == m for o in self.wallet_outcomes):
                continue
            self.wallet_outcomes.append(
                OutcomeLabel(subject=w, mint=m, labeled_at=ts, label=lab, label_version=label_version)
            )
        c = (creator or "").strip()
        if c and not any(o.subject == c and o.mint == m for o in self.creator_outcomes):
            self.creator_outcomes.append(
                OutcomeLabel(subject=c, mint=m, labeled_at=ts, label=lab, label_version=label_version)
            )
        fp = (fingerprint or "").strip()
        if fp and not any(o.subject == fp and o.mint == m for o in self.fingerprint_outcomes):
            self.fingerprint_outcomes.append(
                OutcomeLabel(subject=fp, mint=m, labeled_at=ts, label=lab, label_version=label_version)
            )

    def wallet_performance_as_of(
        self,
        wallets: Iterable[str],
        *,
        as_of: Any = None,
        exclude_mint: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Prior track records only. Insufficient sample is not smart money."""
        cutoff = _parse_ts(as_of)
        exclude = (exclude_mint or "").strip()
        out: dict[str, dict[str, Any]] = {}
        wanted = {(w or "").strip() for w in wallets if w}
        for w in wanted:
            if not is_rankable_wallet(w):
                continue
            mints = {
                o.mint
                for o in self.wallet_obs
                if o.wallet == w and o.mint != exclude and _before(o.observed_at, cutoff)
            }
            labels = [
                o
                for o in self.wallet_outcomes
                if o.subject == w and o.mint != exclude and o.mint in mints and _before(o.labeled_at, cutoff)
            ]
            obs = [
                o for o in self.wallet_obs
                if o.wallet == w and o.mint != exclude and _before(o.observed_at, cutoff)
            ]
            runners = sum(1 for o in labels if o.label == "RUNNER")
            fades = sum(1 for o in labels if o.label == "FADE")
            held = sum(1 for o in labels if o.label == "HELD")
            unknown = sum(1 for o in labels if o.label == "UNKNOWN")
            resolved = runners + fades + held
            hit = (runners / resolved) if resolved else None
            rets = [o.ret_pct for o in obs if o.ret_pct is not None]
            avg_ret = (sum(rets) / len(rets)) if rets else None
            med_ret = (sorted(rets)[len(rets) // 2] if rets else None)
            first_seen = min((o.observed_at for o in obs), default=None)
            last_seen = max((o.observed_at for o in obs), default=None)
            out[w] = {
                "early_buy_count": len(mints),
                "tokens_purchased": len(mints),
                "tokens_observed": len(mints),
                "early_entries": len(mints),
                "hit_rate": hit,
                "avg_return_pct": avg_ret,  # only from stored returns, never fabricated
                "median_return_pct": med_ret,
                "runners": runners,
                "fades": fades,
                "held": held,
                "unknown": unknown,
                "runner_count": runners,
                "held_count": held,
                "fade_count": fades,
                "unknown_count": unknown,
                "runner_participations": runners,
                "sample_size": len(mints),
                "sample_resolved": resolved,
                "first_seen": first_seen.isoformat() if first_seen else None,
                "last_seen": last_seen.isoformat() if last_seen else None,
                "as_of": cutoff.isoformat() if cutoff else None,
                "exclude_mint": exclude or None,
                "source": MEMORY_VERSION,
            }
        return out

    def creator_profile_as_of(
        self,
        creator: str | None,
        *,
        as_of: Any = None,
        exclude_mint: str | None = None,
    ) -> dict[str, Any] | None:
        c = (creator or "").strip()
        if not c:
            return None
        cutoff = _parse_ts(as_of)
        exclude = (exclude_mint or "").strip()
        launches = [
            o for o in self.creator_obs
            if o.wallet == c and o.mint != exclude and _before(o.observed_at, cutoff)
        ]
        if not launches:
            return None
        labels = [
            o for o in self.creator_outcomes
            if o.subject == c and o.mint != exclude and _before(o.labeled_at, cutoff)
        ]
        runners = sum(1 for o in labels if o.label == "RUNNER")
        fades = sum(1 for o in labels if o.label == "FADE")
        held = sum(1 for o in labels if o.label == "HELD")
        unknown = sum(1 for o in labels if o.label == "UNKNOWN")
        resolved = runners + fades + held
        success_rate = (runners / resolved) if resolved >= 3 else None
        times = sorted(o.observed_at for o in launches)
        gaps = [(times[i] - times[i - 1]).total_seconds() for i in range(1, len(times))]
        median_gap = sorted(gaps)[len(gaps) // 2] if gaps else None
        prior_mints = {o.mint for o in launches}
        buyer_counts: dict[str, int] = {}
        for o in self.wallet_obs:
            if o.mint in prior_mints and o.role == "early_buyer" and _before(o.observed_at, cutoff):
                buyer_counts[o.wallet] = buyer_counts.get(o.wallet, 0) + 1
        recurring = sum(1 for n in buyer_counts.values() if n >= 2)
        return {
            "known": True,
            "entity_id": None,
            "launch_count": len(launches),
            "migration_count": sum(1 for o in launches if o.source != "observed_unmigrated"),
            "historical_runners": runners,
            "historical_fades": fades,
            "historical_held": held,
            "historical_unknown": unknown,
            "success_rate": success_rate,
            "median_seconds_between_launches": median_gap,
            "recurring_buyers": recurring,
            "first_seen": times[0].isoformat() if times else None,
            "last_seen": times[-1].isoformat() if times else None,
            "as_of": cutoff.isoformat() if cutoff else None,
            "source": MEMORY_VERSION,
        }

    def relationships_as_of(
        self,
        wallets: Iterable[str],
        *,
        as_of: Any = None,
        exclude_mint: str | None = None,
        min_shared: int = 2,
    ) -> dict[str, Any]:
        cutoff = _parse_ts(as_of)
        exclude = (exclude_mint or "").strip()
        wanted = {(w or "").strip() for w in wallets if w}
        # shared mints from prior co-observation, not just recorded edges
        mint_wallets: dict[str, set[str]] = {}
        for o in self.wallet_obs:
            if o.mint == exclude or not _before(o.observed_at, cutoff):
                continue
            if o.role != "early_buyer":
                continue
            mint_wallets.setdefault(o.mint, set()).add(o.wallet)
        pair_mints: dict[tuple[str, str], set[str]] = {}
        for mint, ws in mint_wallets.items():
            present = sorted(w for w in ws if w in wanted)
            for i, a in enumerate(present):
                for b in present[i + 1 :]:
                    pair_mints.setdefault((a, b), set()).add(mint)
        links = []
        for (a, b), mints in pair_mints.items():
            shared = len(mints)
            if shared < min_shared:
                continue
            conf = 0.55 if shared >= 2 else 0.0
            if shared >= 5:
                conf = 0.70
            if shared >= 8:
                conf = 0.85
            links.append({
                "wallet_a": a,
                "wallet_b": b,
                "kind": "co_buy",
                "shared_mints": shared,
                "prior_mint_count": shared,
                "evidence_count": shared,
                "first_seen": None,
                "last_seen": None,
                "confidence": conf,
                "reason": "co_early_buy" if shared < 8 else "strong_co_early_buy",
                "evidence": {"mints": sorted(mints)[:12], "sample": shared},
                "source": MEMORY_VERSION,
            })
        links.extend(self.deployer_buyer_as_of(wanted, as_of=as_of, exclude_mint=exclude_mint, min_shared=min_shared))
        return {
            "status": "KNOWN" if links else "UNKNOWN",
            "links": links,
            "link_count": len(links),
            "missing": [] if links else ["prior_co_buy"],
        }

    def deployer_buyer_as_of(
        self,
        wallets: Iterable[str],
        *,
        as_of: Any = None,
        exclude_mint: str | None = None,
        min_shared: int = 2,
    ) -> list[dict[str, Any]]:
        """Same wallet bought ≥ min_shared prior mints of the same creator. No identity merge."""
        cutoff = _parse_ts(as_of)
        exclude = (exclude_mint or "").strip()
        wanted = {(w or "").strip() for w in wallets if w}
        creator_mints: dict[str, set[str]] = {}
        for o in self.creator_obs:
            if o.mint == exclude or not _before(o.observed_at, cutoff):
                continue
            creator_mints.setdefault(o.wallet, set()).add(o.mint)
        wallet_mints: dict[str, set[str]] = {}
        for o in self.wallet_obs:
            if o.mint == exclude or not _before(o.observed_at, cutoff):
                continue
            if o.role != "early_buyer" or o.wallet not in wanted:
                continue
            wallet_mints.setdefault(o.wallet, set()).add(o.mint)
        out: list[dict[str, Any]] = []
        for w, wm in wallet_mints.items():
            for c, cm in creator_mints.items():
                if w == c:
                    continue
                shared = wm & cm
                if len(shared) < min_shared:
                    continue
                out.append({
                    "wallet_a": min(w, c),
                    "wallet_b": max(w, c),
                    "kind": "deployer_buyer",
                    "shared_mints": len(shared),
                    "confidence": 0.55 if len(shared) < 5 else 0.70,
                    "reason": "repeat_deployer_buyer",
                    "evidence": {"mints": sorted(shared)[:12], "sample": len(shared), "creator": c, "buyer": w},
                    "source": MEMORY_VERSION,
                })
        return out

    def pattern_match_as_of(
        self,
        fingerprint: str | None,
        *,
        as_of: Any = None,
        exclude_mint: str | None = None,
        min_sample: int = 5,
    ) -> dict[str, Any]:
        fp = (fingerprint or "").strip()
        if not fp:
            return {"similar_runner_count": None, "sample_count": 0, "confidence": "UNKNOWN", "missing": ["fingerprint"]}
        informative = [p for p in fp.split("|") if p and not p.endswith("U")]
        if len(informative) < 3:
            return {
                "similar_runner_count": None,
                "sample_count": 0,
                "confidence": "UNKNOWN",
                "missing": ["fingerprint_informative"],
                "note": "fingerprint has too few observed bands to claim resemblance",
                "runner_pattern": False,
                "fade_pattern": False,
                "calibrated_probability": False,
            }
        cutoff = _parse_ts(as_of)
        exclude = (exclude_mint or "").strip()
        prior = [
            r for r in self.fingerprints
            if r.fingerprint == fp and r.mint != exclude and _before(r.observed_at, cutoff)
        ]
        labels = [
            o for o in self.fingerprint_outcomes
            if o.subject == fp and o.mint != exclude and _before(o.labeled_at, cutoff)
        ]
        runners = sum(1 for o in labels if o.label == "RUNNER")
        fades = sum(1 for o in labels if o.label == "FADE")
        held = sum(1 for o in labels if o.label == "HELD")
        unknown = sum(1 for o in labels if o.label == "UNKNOWN")
        sample = len(prior)
        matching = [r.mint for r in prior]
        support = {
            "RUNNER": runners,
            "HELD": held,
            "FADE": fades,
            "UNKNOWN": unknown,
        }
        base = {
            "similar_runner_count": None,
            "sample_count": sample,
            "runner_matches": runners,
            "held_matches": held,
            "fade_matches": fades,
            "unknown_matches": unknown,
            "matching_historical_mints": matching[:24],
            "pattern_support": support,
            "runner_pattern": False,
            "fade_pattern": False,
            "success_count": runners,
            "failure_count": fades,
            "confidence": "UNKNOWN",
            "missing": [],
            "calibrated_probability": False,
        }
        if sample < min_sample:
            base["missing"] = ["historical_similarity_sample"]
            base["note"] = f"fingerprint seen {sample} times as-of; need ≥{min_sample} to claim resemblance"
            return base
        base["similar_runner_count"] = runners
        base["confidence"] = round(min(0.8, 0.2 + 0.08 * sample), 2)
        base["runner_pattern"] = runners >= 3 and runners > fades
        base["fade_pattern"] = fades >= 3 and fades > runners
        return base

    def ingest_decision(
        self,
        *,
        mint: str,
        observed_at: Any,
        buyers: list[dict[str, Any]] | None = None,
        creator: str | None = None,
        fingerprint: str | None = None,
        features: dict[str, Any] | None = None,
    ) -> None:
        """Record what was observed at decision time. Not the future outcome."""
        ts = observed_at
        for b in buyers or []:
            w = str(b.get("wallet") or b.get("userAddress") or "").strip()
            spent = b.get("sol_spent") if b.get("sol_spent") is not None else b.get("amountSol")
            try:
                spent_f = float(spent) if spent is not None else None
            except (TypeError, ValueError):
                spent_f = None
            self.record_wallet(
                wallet=w, mint=mint, observed_at=ts, sol_spent=spent_f,
                side=str(b.get("side") or b.get("type") or "buy"),
                entry_price=_maybe_float(b.get("entry_price") if b.get("entry_price") is not None else b.get("price")),
                exit_size=_maybe_float(b.get("exit_size")),
                exit_price=_maybe_float(b.get("exit_price")),
                ret_pct=_maybe_float(b.get("ret_pct") if b.get("ret_pct") is not None else b.get("return_pct")),
            )
        if creator:
            self.record_creator(creator=creator, mint=mint, observed_at=ts)
        if fingerprint:
            self.record_fingerprint(fingerprint=fingerprint, mint=mint, observed_at=ts, features=features)

    def snapshot_rows(self) -> dict[str, list[dict[str, Any]]]:
        """SQL-ready dump. Used to persist and to hydrate a fresh process."""
        def _iso(v: Any) -> Any:
            if isinstance(v, datetime):
                return v.isoformat()
            return v

        wallet_obs = [
            {"wallet": o.wallet, "mint": o.mint, "observed_at": _iso(o.observed_at),
             "role": o.role, "sol_spent": o.sol_spent, "source": o.source,
             "side": o.side, "entry_price": o.entry_price, "exit_size": o.exit_size,
             "exit_price": o.exit_price, "ret_pct": o.ret_pct}
            for o in self.wallet_obs
        ]
        wallet_outcomes = [
            {"subject": o.subject, "wallet": o.subject, "mint": o.mint, "labeled_at": _iso(o.labeled_at),
             "label": o.label, "label_version": o.label_version, "source": o.label_version}
            for o in self.wallet_outcomes
        ]
        creator_obs = [
            {"wallet": o.wallet, "creator": o.wallet, "mint": o.mint, "observed_at": _iso(o.observed_at),
             "role": "creator", "sol_spent": None, "source": o.source,
             "migrated": o.source != "observed_unmigrated"}
            for o in self.creator_obs
        ]
        creator_outcomes = [
            {"subject": o.subject, "creator": o.subject, "mint": o.mint, "labeled_at": _iso(o.labeled_at),
             "label": o.label, "label_version": o.label_version}
            for o in self.creator_outcomes
        ]
        fingerprints = [
            {"fingerprint": r.fingerprint, "mint": r.mint, "observed_at": _iso(r.observed_at),
             "features": dict(r.features)}
            for r in self.fingerprints
        ]
        fingerprint_outcomes = [
            {"subject": o.subject, "fingerprint": o.subject, "mint": o.mint, "labeled_at": _iso(o.labeled_at),
             "label": o.label, "label_version": o.label_version}
            for o in self.fingerprint_outcomes
        ]
        relationships = [
            {"wallet_a": e.wallet_a, "wallet_b": e.wallet_b, "kind": e.kind, "mint": e.mint,
             "observed_at": _iso(e.observed_at), "confidence": e.confidence, "reason": e.reason,
             "evidence": dict(e.evidence)}
            for e in self.relationships
        ]
        return {
            "wallet_obs": wallet_obs,
            "wallet_outcomes": wallet_outcomes,
            "creator_obs": creator_obs,
            "creator_outcomes": creator_outcomes,
            "fingerprints": fingerprints,
            "fingerprint_outcomes": fingerprint_outcomes,
            "relationships": relationships,
        }

    def load_wallet_obs(self, rows: Iterable[Any]) -> int:
        n = 0
        for r in rows:
            d = dict(r)
            if self.record_wallet(
                wallet=str(d.get("wallet") or ""),
                mint=str(d.get("mint") or ""),
                observed_at=d.get("observed_at"),
                role=str(d.get("role") or "early_buyer"),
                sol_spent=d.get("sol_spent") if d.get("sol_spent") is None else float(d.get("sol_spent")),
                source=str(d.get("source") or "observed"),
                side=str(d.get("side") or "buy"),
                entry_price=_maybe_float(d.get("entry_price")),
                exit_size=_maybe_float(d.get("exit_size")),
                exit_price=_maybe_float(d.get("exit_price")),
                ret_pct=_maybe_float(d.get("ret_pct")),
            ):
                n += 1
        return n

    def load_wallet_outcomes(self, rows: Iterable[Any]) -> int:
        n = 0
        for r in rows:
            d = dict(r)
            before = len(self.wallet_outcomes)
            self.record_outcome(
                mint=str(d.get("mint") or ""),
                labeled_at=d.get("labeled_at"),
                label=str(d.get("label") or "UNKNOWN"),
                wallets=[str(d.get("subject") or d.get("wallet") or "")],
                label_version=str(d.get("label_version") or "outcome-v1.0.0"),
            )
            n += len(self.wallet_outcomes) - before
        return n

    def load_creator_obs(self, rows: Iterable[Any]) -> int:
        n = 0
        for r in rows:
            d = dict(r)
            if self.record_creator(
                creator=str(d.get("wallet") or d.get("creator") or ""),
                mint=str(d.get("mint") or ""),
                observed_at=d.get("observed_at"),
                migrated=d.get("migrated") if d.get("migrated") is not None else True,
            ):
                n += 1
        return n

    def load_creator_outcomes(self, rows: Iterable[Any]) -> int:
        n = 0
        for r in rows:
            d = dict(r)
            before = len(self.creator_outcomes)
            self.record_outcome(
                mint=str(d.get("mint") or ""),
                labeled_at=d.get("labeled_at"),
                label=str(d.get("label") or "UNKNOWN"),
                creator=str(d.get("subject") or d.get("creator") or ""),
                label_version=str(d.get("label_version") or "outcome-v1.0.0"),
            )
            n += len(self.creator_outcomes) - before
        return n

    def load_fingerprints(self, rows: Iterable[Any]) -> int:
        n = 0
        for r in rows:
            d = dict(r)
            feats = d.get("features") if isinstance(d.get("features"), dict) else {}
            if self.record_fingerprint(
                fingerprint=str(d.get("fingerprint") or ""),
                mint=str(d.get("mint") or ""),
                observed_at=d.get("observed_at"),
                features=feats,
            ):
                n += 1
        return n

    def load_fingerprint_outcomes(self, rows: Iterable[Any]) -> int:
        n = 0
        for r in rows:
            d = dict(r)
            before = len(self.fingerprint_outcomes)
            self.record_outcome(
                mint=str(d.get("mint") or ""),
                labeled_at=d.get("labeled_at"),
                label=str(d.get("label") or "UNKNOWN"),
                fingerprint=str(d.get("subject") or d.get("fingerprint") or ""),
                label_version=str(d.get("label_version") or "outcome-v1.0.0"),
            )
            n += len(self.fingerprint_outcomes) - before
        return n

    def hydrate(self, snapshot: dict[str, Any] | None) -> dict[str, int]:
        snap = snapshot or {}
        return {
            "wallet_obs": self.load_wallet_obs(snap.get("wallet_obs") or []),
            "wallet_outcomes": self.load_wallet_outcomes(snap.get("wallet_outcomes") or []),
            "creator_obs": self.load_creator_obs(snap.get("creator_obs") or []),
            "creator_outcomes": self.load_creator_outcomes(snap.get("creator_outcomes") or []),
            "fingerprints": self.load_fingerprints(snap.get("fingerprints") or []),
            "fingerprint_outcomes": self.load_fingerprint_outcomes(snap.get("fingerprint_outcomes") or []),
        }

    def to_stats(self) -> dict[str, int]:
        return {
            "wallet_observations": len(self.wallet_obs),
            "wallet_outcomes": len(self.wallet_outcomes),
            "creator_observations": len(self.creator_obs),
            "creator_outcomes": len(self.creator_outcomes),
            "relationships": len(self.relationships),
            "fingerprints": len(self.fingerprints),
            "fingerprint_outcomes": len(self.fingerprint_outcomes),
        }


def dump_observation(o: Any) -> dict[str, Any]:
    if hasattr(o, "__dataclass_fields__"):
        d = asdict(o)
        for k, v in list(d.items()):
            if isinstance(v, datetime):
                d[k] = v.isoformat()
        return d
    return dict(o)
