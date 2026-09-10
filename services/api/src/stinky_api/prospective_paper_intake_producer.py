"""Prospective live-intelligence -> frozen paper-intake producer.

This worker starts from an explicit prospective epoch and never backfills pre-start
alerts into T0 decisions. Each new immutable ``alert.candidate`` event becomes a
versioned evidence cohort occurrence and a frozen T0 candidate. Existing
calibration functions are evaluated strictly ``as_of`` the event ingestion time.
A separate later close intake may attach a post-horizon market snapshot, but the
T0 probability/context/policy bundle is copied byte-for-byte and never rebuilt.

No Solana RPC is contacted here. No transaction is signed or submitted. No wallet
is mutated. Missing policy, history, prices, or outcomes remains UNKNOWN.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from stinky_api.calibrated_probability_distributions import build_calibrated_probability_distributions
from stinky_api.counterfactual_journal import build_counterfactual_journal_entry
from stinky_api.db import SessionLocal
from stinky_api.market_pattern_calibration_evaluation import evaluate_pattern_calibration_out_of_sample
from stinky_api.market_pattern_calibration_readiness import assess_pattern_calibration_readiness
from stinky_api.market_pattern_outcome_calibration import calibrate_market_pattern_outcomes
from stinky_api.market_pattern_outcome_distribution import summarize_pattern_outcome_distribution
from stinky_api.market_path_patterns import canonical_pattern_hash
from stinky_api.paper_runtime_worker import canonical_sha256

try:
    from stinky_core.admission import FILTER_VERSION
except Exception:  # pragma: no cover - package is installed in Genesis runtime
    FILTER_VERSION = "UNKNOWN"

PRODUCER_VERSION = "prospective-paper-v1"
_ALLOWED_HORIZONS = {
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "24h": 86400,
}
_AUTHORITY = {
    "paper_only": True,
    "live_execution": False,
    "trading_authority": False,
    "trade_signal": False,
    "rpc_contacted": False,
    "transaction_signed": False,
    "order_submitted": False,
    "wallet_mutated": False,
}


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        raw = str(value or "").strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def cohort_signature(filter_version: str) -> dict[str, Any]:
    """Versioned prospective cohort; contains no future market information."""
    return {
        "paper_runtime_cohort": "prospective_alert_candidate",
        "producer_version": PRODUCER_VERSION,
        "filter_version": str(filter_version or "UNKNOWN"),
        "source_event_type": "alert.candidate",
    }


def paper_configuration_from_env(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Read caller/operator supplied paper policy. No threshold defaults exist."""
    source = os.environ if env is None else env
    policy = {
        "policy_version": str(source.get("STINKY_PAPER_POLICY_VERSION") or "").strip(),
        "horizon": str(source.get("STINKY_PAPER_HORIZON") or "").strip(),
        "min_runner_probability": _num(source.get("STINKY_PAPER_MIN_RUNNER_PROBABILITY")),
        "max_fade_probability": _num(source.get("STINKY_PAPER_MAX_FADE_PROBABILITY")),
        "min_nonnegative_market_cap_probability": _num(source.get("STINKY_PAPER_MIN_NONNEGATIVE_MARKET_CAP_PROBABILITY")),
    }
    assumptions = {
        "entry_slippage_bps": _num(source.get("STINKY_PAPER_ENTRY_SLIPPAGE_BPS")),
        "exit_slippage_bps": _num(source.get("STINKY_PAPER_EXIT_SLIPPAGE_BPS")),
        "entry_fee_bps": _num(source.get("STINKY_PAPER_ENTRY_FEE_BPS")),
        "exit_fee_bps": _num(source.get("STINKY_PAPER_EXIT_FEE_BPS")),
        "latency_ms": _num(source.get("STINKY_PAPER_LATENCY_MS")),
    }
    notional = _num(source.get("STINKY_PAPER_NOTIONAL_USD"))
    missing: list[str] = []
    if not policy["policy_version"]:
        missing.append("STINKY_PAPER_POLICY_VERSION")
    if policy["horizon"] not in _ALLOWED_HORIZONS:
        missing.append("STINKY_PAPER_HORIZON")
    for key in ("min_runner_probability", "max_fade_probability", "min_nonnegative_market_cap_probability"):
        value = policy[key]
        if value is None or not (0.0 <= value <= 1.0):
            missing.append("STINKY_PAPER_" + key.upper())
    for key, value in assumptions.items():
        if value is None or value < 0:
            missing.append("STINKY_PAPER_" + key.upper())
    if notional is None or notional <= 0 or notional > 20.0:
        missing.append("STINKY_PAPER_NOTIONAL_USD")
    return {
        "configured": not missing,
        "missing": missing,
        "paper_policy": policy,
        "execution_assumptions": assumptions,
        "paper_notional_usd": notional,
        **_AUTHORITY,
    }


async def _producer_epoch(session) -> datetime:
    row = (
        await session.execute(
            text("SELECT prospective_started_at FROM paper_intake_producer_state WHERE singleton=TRUE")
        )
    ).first()
    if row:
        return row[0]
    now = datetime.now(timezone.utc)
    await session.execute(
        text(
            """
            INSERT INTO paper_intake_producer_state(singleton, producer_version, prospective_started_at)
            VALUES (TRUE, :version, :started)
            ON CONFLICT (singleton) DO NOTHING
            """
        ),
        {"version": PRODUCER_VERSION, "started": now},
    )
    await session.commit()
    row = (
        await session.execute(
            text("SELECT prospective_started_at FROM paper_intake_producer_state WHERE singleton=TRUE")
        )
    ).first()
    return row[0] if row else now


async def _persist_cohort_occurrence(session, *, mint: str, decided_at: datetime, signature: dict[str, Any]) -> str:
    pattern_hash = canonical_pattern_hash(signature)
    payload = json.dumps(signature, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    await session.execute(
        text(
            """
            INSERT INTO market_path_patterns(
                pattern_hash, signature, evidence_basis,
                first_observed_at, last_observed_at, occurrence_count
            ) VALUES (
                :hash, CAST(:signature AS jsonb), 'prospective_alert_candidate_cohort',
                :observed, :observed, 0
            ) ON CONFLICT (pattern_hash) DO NOTHING
            """
        ),
        {"hash": pattern_hash, "signature": payload, "observed": decided_at},
    )
    inserted = (
        await session.execute(
            text(
                """
                INSERT INTO market_path_pattern_occurrences(
                    pattern_hash, mint, observed_at, source, evidence_basis, signature
                ) VALUES (
                    :hash, :mint, :observed, 'prospective_paper_intake_producer',
                    'prospective_alert_candidate_cohort', CAST(:signature AS jsonb)
                ) ON CONFLICT DO NOTHING RETURNING id
                """
            ),
            {"hash": pattern_hash, "mint": mint, "observed": decided_at, "signature": payload},
        )
    ).first()
    if inserted:
        await session.execute(
            text(
                """
                UPDATE market_path_patterns
                SET occurrence_count=occurrence_count+1,
                    first_observed_at=LEAST(first_observed_at,:observed),
                    last_observed_at=GREATEST(last_observed_at,:observed),
                    updated_at=now()
                WHERE pattern_hash=:hash
                """
            ),
            {"hash": pattern_hash, "observed": decided_at},
        )
    return pattern_hash


async def _journal_as_of(session, pattern_hash: str, as_of: datetime) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT mint, decided_at, t0_evidence, canonical_outcome,
                       outcome_observed_at, outcome_event_id
                FROM paper_prospective_candidate
                WHERE cohort_pattern_hash=:hash
                  AND decided_at < :as_of
                  AND canonical_outcome IN ('RUNNER','HELD','FADE')
                  AND outcome_observed_at IS NOT NULL
                  AND outcome_observed_at <= :as_of
                ORDER BY decided_at ASC, candidate_id ASC
                """
            ),
            {"hash": pattern_hash, "as_of": as_of},
        )
    ).mappings().all()
    entries: list[dict[str, Any]] = []
    for row in rows:
        decision = {
            "mint": row["mint"],
            "decided_at": row["decided_at"],
            "action": "WOULD_WATCH",
            "evidence_snapshot": row["t0_evidence"],
            "reason_codes": ["prospective_calibration_watch"],
            "policy_version": PRODUCER_VERSION,
            "temporal_cutoff_enforced": True,
            "future_evidence_used": False,
        }
        outcome = {
            "label": row["canonical_outcome"],
            "completed_at": row["outcome_observed_at"],
            "canonical_classification": True,
            "evidence_basis": "immutable_post_migration_tracking_completed_event",
            "source_table": "events",
            "event_id": row["outcome_event_id"],
        }
        entry = build_counterfactual_journal_entry(decision, outcome)
        if entry.get("status") == "OBSERVED":
            entries.append(entry)
    return entries


async def _probability_as_of(session, pattern_hash: str, as_of: datetime) -> dict[str, Any]:
    calibration = await calibrate_market_pattern_outcomes(session, pattern_hash, occurrence_limit=500, as_of=as_of)
    distribution = summarize_pattern_outcome_distribution(calibration)
    readiness = assess_pattern_calibration_readiness(calibration)
    evaluation = evaluate_pattern_calibration_out_of_sample(calibration, readiness)
    journal = await _journal_as_of(session, pattern_hash, as_of)
    return build_calibrated_probability_distributions(
        calibration, distribution, evaluation, journal, min_closed_outcomes=5
    )


async def _entry_price_as_of(session, mint: str, as_of: datetime, payload: dict[str, Any]) -> float | None:
    direct = _num(payload.get("price_usd"))
    if direct is not None and direct > 0:
        return direct
    row = (
        await session.execute(
            text(
                """
                SELECT price_usd FROM market_snapshots
                WHERE mint=:mint AND captured_at <= :as_of AND price_usd > 0
                ORDER BY captured_at DESC, snapshot_id DESC LIMIT 1
                """
            ),
            {"mint": mint, "as_of": as_of},
        )
    ).first()
    value = _num(row[0]) if row else None
    return value if value is not None and value > 0 else None


async def _freeze_new_candidates(session, limit: int = 25) -> int:
    started = await _producer_epoch(session)
    rows = (
        await session.execute(
            text(
                """
                SELECT e.event_id::text AS event_id, e.occurred_at, e.ingested_at,
                       e.producer, e.signature, e.payload
                FROM events e
                LEFT JOIN paper_prospective_candidate c ON c.source_event_id=e.event_id::text
                WHERE e.event_type='alert.candidate'
                  AND e.ingested_at >= :started
                  AND c.source_event_id IS NULL
                ORDER BY e.ingested_at ASC, e.event_id ASC
                LIMIT :limit
                """
            ),
            {"started": started, "limit": limit},
        )
    ).mappings().all()
    config = paper_configuration_from_env()
    count = 0
    for row in rows:
        payload = row["payload"] if isinstance(row["payload"], dict) else {}
        mint = str(payload.get("mint") or "").strip()
        occurred = _dt(row["occurred_at"])
        ingested = _dt(row["ingested_at"])
        if not mint or occurred is None or ingested is None or ingested < occurred:
            continue
        decided_at = ingested  # earliest durable time Genesis can prove it knew the event
        filter_version = str(FILTER_VERSION or "UNKNOWN")
        signature = cohort_signature(filter_version)
        pattern_hash = await _persist_cohort_occurrence(
            session, mint=mint, decided_at=decided_at, signature=signature
        )
        evidence = {
            "source_event": {
                "event_id": row["event_id"],
                "event_type": "alert.candidate",
                "occurred_at": occurred.isoformat(),
                "ingested_at": ingested.isoformat(),
                "producer": row["producer"],
                "signature": row["signature"],
                "payload": copy.deepcopy(payload),
            },
            "producer_version": PRODUCER_VERSION,
            "filter_version": filter_version,
            "cohort_pattern_hash": pattern_hash,
            "temporal_cutoff_enforced": True,
            "future_evidence_used": False,
        }
        evidence_hash = canonical_sha256(evidence)
        probability = await _probability_as_of(session, pattern_hash, decided_at)
        entry_price = await _entry_price_as_of(session, mint, decided_at, payload)
        bundle: dict[str, Any] | None = None
        bundle_hash: str | None = None
        open_intake_id: str | None = None
        close_due: datetime | None = None
        if config["configured"] and entry_price is not None:
            horizon = config["paper_policy"]["horizon"]
            close_due = decided_at + timedelta(seconds=_ALLOWED_HORIZONS[horizon])
            bundle = {
                "probability_distribution": probability,
                "decision_context": {
                    "mint": mint,
                    "decided_at": decided_at.isoformat(),
                    "evidence_snapshot": copy.deepcopy(evidence),
                    "temporal_cutoff_enforced": True,
                    "future_evidence_used": False,
                },
                "paper_policy": copy.deepcopy(config["paper_policy"]),
                "execution_assumptions": copy.deepcopy(config["execution_assumptions"]),
                "reference_entry_price": entry_price,
                "paper_notional_usd": config["paper_notional_usd"],
            }
            bundle_hash = canonical_sha256(bundle)
            open_intake_id = "prospective:%s:open" % row["event_id"]
        await session.execute(
            text(
                """
                INSERT INTO paper_prospective_candidate(
                    candidate_id, source_event_id, mint, decided_at,
                    source_event_occurred_at, source_event_ingested_at,
                    producer_version, filter_version, cohort_pattern_hash,
                    t0_evidence, t0_evidence_sha256, frozen_bundle,
                    frozen_bundle_sha256, reference_entry_price, close_due_at,
                    open_intake_id
                ) VALUES (
                    :candidate_id,:event_id,:mint,:decided,:occurred,:ingested,
                    :producer_version,:filter_version,:pattern_hash,
                    CAST(:evidence AS jsonb),:evidence_hash,CAST(:bundle AS jsonb),
                    :bundle_hash,:entry_price,:close_due,:open_intake_id
                ) ON CONFLICT (candidate_id) DO NOTHING
                """
            ),
            {
                "candidate_id": row["event_id"], "event_id": row["event_id"], "mint": mint,
                "decided": decided_at, "occurred": occurred, "ingested": ingested,
                "producer_version": PRODUCER_VERSION, "filter_version": filter_version,
                "pattern_hash": pattern_hash,
                "evidence": json.dumps(evidence, sort_keys=True, separators=(",", ":")),
                "evidence_hash": evidence_hash,
                "bundle": json.dumps(bundle, sort_keys=True, separators=(",", ":")) if bundle is not None else None,
                "bundle_hash": bundle_hash, "entry_price": entry_price,
                "close_due": close_due, "open_intake_id": open_intake_id,
            },
        )
        if bundle is not None and open_intake_id is not None:
            await session.execute(
                text(
                    """
                    INSERT INTO paper_runtime_intake(intake_id,mint,observed_at,payload,payload_sha256)
                    VALUES (:id,:mint,:observed,CAST(:payload AS jsonb),:sha)
                    ON CONFLICT (intake_id) DO NOTHING
                    """
                ),
                {
                    "id": open_intake_id, "mint": mint, "observed": decided_at,
                    "payload": json.dumps(bundle, sort_keys=True, separators=(",", ":")),
                    "sha": bundle_hash,
                },
            )
        await session.commit()
        count += 1
    return count


async def _attach_canonical_outcomes(session, limit: int = 50) -> int:
    rows = (
        await session.execute(
            text(
                """
                SELECT c.candidate_id,c.mint,c.decided_at,
                       e.event_id::text AS outcome_event_id,e.occurred_at,e.ingested_at,e.payload
                FROM paper_prospective_candidate c
                JOIN LATERAL (
                    SELECT event_id,occurred_at,ingested_at,payload
                    FROM events
                    WHERE event_type='post_migration.tracking_completed'
                      AND payload->>'mint'=c.mint
                      AND occurred_at > c.decided_at
                      AND ingested_at > c.decided_at
                    ORDER BY occurred_at ASC,ingested_at ASC LIMIT 1
                ) e ON TRUE
                WHERE c.canonical_outcome IS NULL
                ORDER BY c.decided_at ASC LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    ).mappings().all()
    changed = 0
    for row in rows:
        payload = row["payload"] if isinstance(row["payload"], dict) else {}
        raw = payload.get("outcome_status") or payload.get("outcome") or payload.get("status")
        outcome = str(raw or "UNKNOWN").upper()
        if outcome not in {"RUNNER", "HELD", "FADE"}:
            continue
        observed = _dt(row["occurred_at"])
        ingested = _dt(row["ingested_at"])
        decided = _dt(row["decided_at"])
        if observed is None or ingested is None or decided is None:
            continue
        known_at = max(observed, ingested)
        if known_at <= decided:
            continue
        result = await session.execute(
            text(
                """
                UPDATE paper_prospective_candidate
                SET canonical_outcome=:outcome,outcome_observed_at=:known_at,
                    outcome_event_id=:event_id
                WHERE candidate_id=:candidate_id AND canonical_outcome IS NULL
                """
            ),
            {"outcome": outcome, "known_at": known_at, "event_id": row["outcome_event_id"], "candidate_id": row["candidate_id"]},
        )
        if result.rowcount:
            changed += 1
    await session.commit()
    return changed


async def _enqueue_due_closes(session, limit: int = 25) -> int:
    rows = (
        await session.execute(
            text(
                """
                SELECT c.candidate_id,c.mint,c.frozen_bundle,c.frozen_bundle_sha256,
                       c.close_due_at,c.open_intake_id,r.paper_status
                FROM paper_prospective_candidate c
                JOIN paper_runtime_record r ON r.intake_id=c.open_intake_id
                WHERE c.frozen_bundle IS NOT NULL
                  AND c.close_due_at IS NOT NULL AND c.close_due_at <= now()
                  AND c.close_intake_id IS NULL
                  AND r.paper_status='SIMULATED_OPEN'
                ORDER BY c.close_due_at ASC LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    ).mappings().all()
    count = 0
    for row in rows:
        snap = (
            await session.execute(
                text(
                    """
                    SELECT snapshot_id::text AS snapshot_id,captured_at,price_usd,source
                    FROM market_snapshots
                    WHERE mint=:mint AND captured_at >= :due AND price_usd > 0
                    ORDER BY captured_at ASC,snapshot_id ASC LIMIT 1
                    """
                ),
                {"mint": row["mint"], "due": row["close_due_at"]},
            )
        ).mappings().first()
        if not snap:
            continue
        exit_price = _num(snap["price_usd"])
        if exit_price is None or exit_price <= 0:
            continue
        frozen = row["frozen_bundle"] if isinstance(row["frozen_bundle"], dict) else None
        if frozen is None or canonical_sha256(frozen) != row["frozen_bundle_sha256"]:
            continue
        close_payload = copy.deepcopy(frozen)
        close_payload["reference_exit_price"] = exit_price
        close_payload["paper_close_evidence"] = {
            "snapshot_id": snap["snapshot_id"],
            "captured_at": snap["captured_at"].isoformat() if hasattr(snap["captured_at"], "isoformat") else str(snap["captured_at"]),
            "source": snap["source"],
            "strictly_later_than_t0": True,
            "t0_bundle_recomputed": False,
        }
        close_id = "prospective:%s:close" % row["candidate_id"]
        close_hash = canonical_sha256(close_payload)
        await session.execute(
            text(
                """
                INSERT INTO paper_runtime_intake(intake_id,mint,observed_at,payload,payload_sha256)
                VALUES (:id,:mint,:observed,CAST(:payload AS jsonb),:sha)
                ON CONFLICT (intake_id) DO NOTHING
                """
            ),
            {
                "id": close_id, "mint": row["mint"], "observed": snap["captured_at"],
                "payload": json.dumps(close_payload, sort_keys=True, separators=(",", ":")),
                "sha": close_hash,
            },
        )
        result = await session.execute(
            text(
                """
                UPDATE paper_prospective_candidate SET close_intake_id=:close_id
                WHERE candidate_id=:candidate_id AND close_intake_id IS NULL
                """
            ),
            {"close_id": close_id, "candidate_id": row["candidate_id"]},
        )
        if result.rowcount:
            count += 1
    await session.commit()
    return count


async def tick() -> dict[str, Any]:
    async with SessionLocal() as session:
        frozen = await _freeze_new_candidates(session)
        outcomes = await _attach_canonical_outcomes(session)
        closes = await _enqueue_due_closes(session)
        config = paper_configuration_from_env()
        return {
            "status": "OBSERVED",
            "producer_version": PRODUCER_VERSION,
            "new_candidates": frozen,
            "canonical_outcomes_attached": outcomes,
            "close_intakes_enqueued": closes,
            "paper_policy_configured": config["configured"],
            "configuration_missing": config["missing"],
            **_AUTHORITY,
        }


async def run_forever() -> None:
    while True:
        try:
            result = await tick()
            if result["new_candidates"] or result["canonical_outcomes_attached"] or result["close_intakes_enqueued"]:
                print(json.dumps(result, sort_keys=True), flush=True)
        except Exception as exc:
            print(json.dumps({"status": "UNKNOWN", "error": type(exc).__name__, **_AUTHORITY}), flush=True)
        await asyncio.sleep(2.0)


if __name__ == "__main__":
    asyncio.run(run_forever())
