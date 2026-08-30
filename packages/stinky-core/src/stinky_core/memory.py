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

MEMORY_VERSION = "memory-v1.0.0-asof"

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
MEMORY_INDEXES: tuple[str, ...] = ()


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


@dataclass
class WalletObservation:
    wallet: str
    mint: str
    observed_at: datetime
    role: str = "early_buyer"
    sol_spent: float | None = None
    source: str = "observed"


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
            WalletObservation(wallet=w, mint=m, observed_at=ts, role=role, sol_spent=sol_spent, source=source)
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
            runners = sum(1 for o in labels if o.label == "RUNNER")
            fades = sum(1 for o in labels if o.label == "FADE")
            held = sum(1 for o in labels if o.label == "HELD")
            unknown = sum(1 for o in labels if o.label == "UNKNOWN")
            resolved = runners + fades + held
            hit = (runners / resolved) if resolved else None
            out[w] = {
                "early_buy_count": len(mints),
                "tokens_purchased": len(mints),
                "hit_rate": hit,
                "avg_return_pct": None,  # never fabricate returns
                "runners": runners,
                "fades": fades,
                "held": held,
                "unknown": unknown,
                "sample_resolved": resolved,
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
        return {
            "known": True,
            "entity_id": None,
            "launch_count": len(launches),
            "migration_count": sum(1 for o in launches if o.source != "observed_unmigrated"),
            "historical_runners": runners,
            "historical_fades": fades,
            "historical_held": held,
            "historical_unknown": unknown,
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
                "confidence": conf,
                "reason": "co_early_buy" if shared < 8 else "strong_co_early_buy",
                "evidence": {"mints": sorted(mints)[:12], "sample": shared},
                "source": MEMORY_VERSION,
            })
        return {
            "status": "KNOWN" if links else "UNKNOWN",
            "links": links,
            "link_count": len(links),
            "missing": [] if links else ["prior_co_buy"],
        }

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
        sample = len(prior)
        if sample < min_sample:
            return {
                "similar_runner_count": None,
                "sample_count": sample,
                "success_count": runners,
                "failure_count": fades,
                "confidence": "UNKNOWN",
                "missing": ["historical_similarity_sample"],
                "note": f"fingerprint seen {sample} times as-of; need ≥{min_sample} to claim resemblance",
            }
        return {
            "similar_runner_count": runners,
            "sample_count": sample,
            "success_count": runners,
            "failure_count": fades,
            "confidence": round(min(0.8, 0.2 + 0.08 * sample), 2),
            "missing": [],
        }

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
            self.record_wallet(wallet=w, mint=mint, observed_at=ts, sol_spent=spent_f)
        if creator:
            self.record_creator(creator=creator, mint=mint, observed_at=ts)
        if fingerprint:
            self.record_fingerprint(fingerprint=fingerprint, mint=mint, observed_at=ts, features=features)

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
