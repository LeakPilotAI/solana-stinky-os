"""Genesis coordination. Assembler over existing organs. Not a second engine.

Canonical identity is correlation_id (mint + gate1_at). Evidence quality is
LIVE | FIXTURE | SIMULATION | HISTORICAL. UNKNOWN stays UNKNOWN.
No ML. No trading. Gate 1 stays $150k / 5m, clamp $200k.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from stinky_core.admission import (
    GATE1_VOLUME_5M_USD,
    GATE1_VOLUME_CALIBRATION_MAX_USD,
    clamp_gate1_volume,
    evaluate_gate1,
)
from stinky_core.book import outcome_from_ticks
from stinky_core.evidence import EvidenceBundle, item as evidence_item
from stinky_core.fingerprint import fingerprint_from_maps
from stinky_core.memory import IntelligenceMemory
from stinky_core.observation import correlation_id, investigation_record, observation_slices
from stinky_core.quality_state import evaluate_quality_state
from stinky_core.recipes import runner_recipe
from stinky_core.similarity import historical_similarity

COORDINATION_VERSION = "intel-v2.0.0-coordination"

QUALITY_LIVE = "LIVE"
QUALITY_FIXTURE = "FIXTURE"
QUALITY_SIMULATION = "SIMULATION"
QUALITY_HISTORICAL = "HISTORICAL"
QUALITIES = (QUALITY_LIVE, QUALITY_FIXTURE, QUALITY_SIMULATION, QUALITY_HISTORICAL)

LIFECYCLE = (
    "DISCOVERED",
    "QUALIFIED",
    "INVESTIGATING",
    "WATCHING",
    "ANALYZING",
    "COMPLETED",
    "FAILED",
    "INTERRUPTED",
    "INCOMPLETE",
    "UNKNOWN",
)


def evidence_atom(
    *,
    what: str,
    value: Any,
    source: str,
    observed_at: str | None,
    as_of: str | None,
    quality: str,
    category: str = "MARKET",
    confidence: float | None = None,
    unknown_reason: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One evidence fact. Missing value → UNKNOWN. Never invents."""
    q = quality if quality in QUALITIES else "UNKNOWN"
    status = "UNKNOWN" if value is None else "OBSERVED"
    reason = unknown_reason
    if value is None and not reason:
        reason = f"{what} not observed"
    ev = evidence_item(
        category,
        what,
        value,
        status=status,
        source=source,
        explanation=reason or source,
        confidence=confidence,
        provenance=provenance or {"source": source, "quality": q},
    )
    d = ev.to_dict()
    d["quality"] = q
    d["observed_at"] = observed_at
    d["as_of"] = as_of
    d["unknown_reason"] = reason if status == "UNKNOWN" else None
    d["calibrated_probability"] = False
    return d


def lifecycle_of(
    *,
    gate_decision: str | None,
    investigation_status: str | None,
    quality_state: str | None,
    outcome_label: str | None,
    interrupted: bool = False,
) -> str:
    """Map stored fields onto the explicit pipeline. Never inferred from UI."""
    if interrupted:
        return "INTERRUPTED"
    gd = (gate_decision or "").upper()
    st = (investigation_status or "").upper()
    qs = (quality_state or "").upper()
    oc = (outcome_label or "").upper()
    if gd == "REJECTED" or st == "REJECTED":
        return "FAILED"
    if oc in ("RUNNER", "HELD", "FADE", "RUG") and oc != "UNKNOWN":
        return "COMPLETED"
    if qs in ("FAILED", "SEVERE_DETERIORATION"):
        return "ANALYZING"
    if st in ("WATCHING", "DETECTED"):
        return "WATCHING"
    if st in ("INVESTIGATING", "INVESTIGATION"):
        return "INVESTIGATING"
    if gd == "PASSED" or st == "QUALIFIED":
        return "QUALIFIED"
    if gd or st:
        return "DISCOVERED"
    return "UNKNOWN"


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat()
    s = str(v).strip()
    return s or None


def assemble_investigation(
    memory: IntelligenceMemory,
    mint: str,
    *,
    as_of: Any = None,
    quality: str = QUALITY_LIVE,
) -> dict[str, Any]:
    """One coordinated case file from existing stores. Empty stays empty."""
    q = quality if quality in QUALITIES else "UNKNOWN"
    rec = next((r for r in memory.investigations if str(r.get("mint")) == mint), None)
    if rec is None:
        return {
            "version": COORDINATION_VERSION,
            "mint": mint,
            "investigation_id": None,
            "quality": q,
            "lifecycle": "UNKNOWN",
            "empty": True,
            "note": "NO ACTIVE INVESTIGATIONS" if not memory.investigations else "mint not in store",
            "calibrated_probability": False,
        }
    t0 = rec.get("gate1_at") or rec.get("decision_timestamp")
    cid = rec.get("correlation_id") or correlation_id(mint, t0)
    slices = observation_slices(memory, mint=mint, t0=t0, as_of=as_of)
    quality_row = evaluate_quality_state(memory, mint=mint, t0=t0, as_of=as_of)
    outcome = outcome_from_ticks(memory, mint=mint, decision_at=t0, now=as_of)
    fp = None
    for row in memory.fingerprints:
        if row.mint == mint:
            fp = row.fingerprint
            break
    analogues = historical_similarity(memory, fp, as_of=as_of, exclude_mint=mint) if fp else {
        "sample_count": 0,
        "similarity_confidence": "UNKNOWN",
        "calibrated_probability": False,
        "note": "no fingerprint",
    }
    recipe = runner_recipe(memory, fp, as_of=as_of, exclude_mint=mint)
    wallets = [w for w in memory.wallet_obs if w.mint == mint]
    creator = rec.get("creator")
    unknown: list[str] = []
    if rec.get("creator") is None:
        unknown.append("creator")
    if not wallets:
        unknown.append("early_buyers")
    if (analogues.get("sample_count") or 0) < 5:
        unknown.append("analogue_sample")
    if (outcome.get("label") or "UNKNOWN") == "UNKNOWN":
        unknown.append("outcome")
    vol = rec.get("volume_5m_at_gate")
    evidence = [
        evidence_atom(
            what="5m_volume",
            value=vol,
            source="investigation.gate1",
            observed_at=_iso(t0),
            as_of=_iso(as_of) or _iso(t0),
            quality=q,
            category="MARKET",
        ),
        evidence_atom(
            what="liquidity",
            value=rec.get("liquidity_at_gate"),
            source="investigation.gate1",
            observed_at=_iso(t0),
            as_of=_iso(as_of) or _iso(t0),
            quality=q,
            category="MARKET",
        ),
        evidence_atom(
            what="creator",
            value=creator,
            source="investigation.gate1",
            observed_at=_iso(t0),
            as_of=_iso(as_of) or _iso(t0),
            quality=q,
            category="CREATOR",
            unknown_reason="creator history unavailable" if creator is None else None,
        ),
        evidence_atom(
            what="early_buyers",
            value=len(wallets) if wallets else None,
            source="wallet_observations",
            observed_at=_iso(t0),
            as_of=_iso(as_of) or _iso(t0),
            quality=q,
            category="WALLETS",
            unknown_reason="early buyers not observed" if not wallets else None,
        ),
    ]
    life = lifecycle_of(
        gate_decision=rec.get("gate_decision"),
        investigation_status=rec.get("investigation_status"),
        quality_state=quality_row.get("state"),
        outcome_label=outcome.get("label"),
        interrupted=bool(rec.get("interrupted")),
    )
    return {
        "version": COORDINATION_VERSION,
        "investigation_id": cid,
        "mint": mint,
        "quality": q,
        "lifecycle": life,
        "identity": rec,
        "gate": {
            "threshold_usd": GATE1_VOLUME_5M_USD,
            "clamp_usd": GATE1_VOLUME_CALIBRATION_MAX_USD,
            "decision": rec.get("gate_decision"),
            "volume_5m_at_gate": vol,
            "not_a_buy": True,
        },
        "evidence": evidence,
        "observations": slices,
        "quality_state": quality_row,
        "entities": {"creator": creator, "wallets": [w.wallet for w in wallets[:20]]},
        "wallets": [{"wallet": w.wallet, "role": w.role, "observed_at": _iso(w.observed_at)} for w in wallets[:20]],
        "analogues": analogues,
        "recipe": recipe,
        "outcome": outcome,
        "unknowns": unknown,
        "links": {
            "token": f"/tokens/{mint}",
            "investigation": "/investigations",
            "observations": "/observations",
            "quality": "/dips",
            "wallets": "/wallets",
            "entities": "/entities",
        },
        "empty": False,
        "calibrated_probability": False,
        "note": "Assembler over IntelligenceMemory. Not a buy. UNKNOWN is not evidence.",
    }


def list_investigations(
    memory: IntelligenceMemory,
    *,
    as_of: Any = None,
    quality: str = QUALITY_LIVE,
    limit: int = 20,
) -> dict[str, Any]:
    q = quality if quality in QUALITIES else "UNKNOWN"
    rows = []
    for rec in memory.investigations[: max(0, int(limit))]:
        mint = str(rec.get("mint") or "")
        if not mint:
            continue
        t0 = rec.get("gate1_at")
        qs = evaluate_quality_state(memory, mint=mint, t0=t0, as_of=as_of)
        oc = outcome_from_ticks(memory, mint=mint, decision_at=t0, now=as_of)
        life = lifecycle_of(
            gate_decision=rec.get("gate_decision"),
            investigation_status=rec.get("investigation_status"),
            quality_state=qs.get("state"),
            outcome_label=oc.get("label"),
        )
        rows.append(
            {
                "investigation_id": rec.get("correlation_id") or correlation_id(mint, t0),
                "mint": mint,
                "quality": q,
                "lifecycle": life,
                "gate_decision": rec.get("gate_decision"),
                "volume_5m_at_gate": rec.get("volume_5m_at_gate"),
                "quality_state": qs.get("state"),
                "outcome": oc.get("label") or "UNKNOWN",
                "unknowns": [],
                "links": {"token": f"/tokens/{mint}"},
                "calibrated_probability": False,
            }
        )
    return {
        "version": COORDINATION_VERSION,
        "quality": q,
        "count": len(rows),
        "investigations": rows,
        "empty_note": "NO ACTIVE INVESTIGATIONS" if not rows else None,
        "calibrated_probability": False,
    }


def run_simulation() -> dict[str, Any]:
    """Deterministic SIMULATION pipeline. Never labeled LIVE."""
    q = QUALITY_SIMULATION
    mem = IntelligenceMemory()
    t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    hist_fp = fingerprint_from_maps(
        {"volume_m5_usd": 180_000, "liquidity_usd": 40_000, "unique_wallets": 20, "buy_sell_imbalance": 0.2},
        {"smart_wallet_count": 1},
        {"launch_count": 3},
    )
    for i, hist_mint in enumerate(("SimHistAAAAAAAAAAAAAAAAAAAAAAAAAAAApump", "SimHistBBBBBBBBBBBBBBBBBBBBBBBBBBBBpump")):
        ht = t0 - timedelta(days=30 + i)
        mem.record_fingerprint(fingerprint=hist_fp, mint=hist_mint, observed_at=ht)
        mem.record_outcome(mint=hist_mint, labeled_at=ht + timedelta(hours=1), label="RUNNER", fingerprint=hist_fp)
    mint = "SimCoordAAAAAAAAAAAAAAAAAAAAAAAAAAAApump"
    vol = 183_400.0
    gate = evaluate_gate1({"mint": mint, "protocol": "pumpswap", "volume_usd": vol, "migrated": True})
    assert gate.eligible is True
    rec = investigation_record(
        {
            "mint": mint,
            "protocol": "pumpswap",
            "volume_usd": vol,
            "liquidity_usd": 55_000,
            "decision_timestamp": t0.isoformat(),
            "creator": None,
        },
        gate1_passed=True,
        investigation_status="WATCHING",
    )
    mem.record_investigation(rec)
    ticks = (
        (0, vol, 1.0, 55_000),
        (15, 190_000, 1.05, 56_000),
        (900, 240_000, 1.8, 70_000),
        (1800, 410_000, 2.4, 80_000),
    )
    for offset, v, px, liq in ticks:
        mem.record_market_tick(
            mint=mint,
            observed_at=t0 + timedelta(seconds=offset),
            volume_m5_usd=v,
            price_usd=px,
            liquidity_usd=liq,
            source="simulation",
        )
    fp = fingerprint_from_maps(
        {"volume_m5_usd": vol, "liquidity_usd": 55_000, "unique_wallets": 20, "buy_sell_imbalance": 0.2},
        {"smart_wallet_count": 1},
        {"launch_count": 3},
    )
    mem.record_fingerprint(fingerprint=fp, mint=mint, observed_at=t0)
    at_t0 = assemble_investigation(mem, mint, as_of=t0, quality=q)
    at_end = assemble_investigation(mem, mint, as_of=t0 + timedelta(seconds=1800), quality=q)
    slices_t0 = at_t0["observations"]["slices"]
    vol_t1800_at_t0 = next((s.get("volume_5m") for s in slices_t0 if s.get("offset_sec") == 1800), None)
    # Last-known carry at T+0 is the T+0 tick, not the future 410k print.
    return {
        "version": COORDINATION_VERSION,
        "quality": q,
        "investigation_id": at_end["investigation_id"],
        "mint": mint,
        "gate_eligible": gate.eligible,
        "gate1_usd": GATE1_VOLUME_5M_USD,
        "clamp_usd": GATE1_VOLUME_CALIBRATION_MAX_USD,
        "lifecycle": at_end["lifecycle"],
        "t0": at_t0,
        "t1800": at_end,
        "future_hidden": vol_t1800_at_t0 != 410_000,
        "live_contaminated": at_end["quality"] == QUALITY_LIVE,
        "calibrated_probability": False,
        "note": "SIMULATION. Not LIVE. Not a buy.",
    }


def assert_gate1_frozen() -> None:
    assert GATE1_VOLUME_5M_USD == 150_000.0
    assert GATE1_VOLUME_CALIBRATION_MAX_USD == 200_000.0
    assert clamp_gate1_volume(250_000) == 200_000.0
