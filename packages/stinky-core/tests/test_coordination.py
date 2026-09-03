"""Intel v2.0 coordination. Assembler, as-of, SIMULATION ≠ LIVE. No ML. No trading."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pathlib import Path

from stinky_core.admission import GATE1_VOLUME_5M_USD, GATE1_VOLUME_CALIBRATION_MAX_USD, clamp_gate1_volume
from stinky_core.coordination import (
    COORDINATION_VERSION,
    QUALITY_LIVE,
    QUALITY_SIMULATION,
    assemble_investigation,
    assert_gate1_frozen,
    evidence_atom,
    lifecycle_of,
    list_investigations,
    run_simulation,
)
from stinky_core.memory import IntelligenceMemory
from stinky_core.observation import investigation_record

ROOT = Path(__file__).resolve().parents[3]

T0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
MINT = "CoordMintAAAAAAAAAAAAAAAAAAAAAAAAAAAApump"


def test_gate1_frozen():
    assert_gate1_frozen()
    assert GATE1_VOLUME_5M_USD == 150_000.0
    assert GATE1_VOLUME_CALIBRATION_MAX_USD == 200_000.0
    assert clamp_gate1_volume(250_000) == 200_000.0


def test_evidence_atom_unknown_is_not_zero():
    atom = evidence_atom(
        what="creator",
        value=None,
        source="test",
        observed_at=T0.isoformat(),
        as_of=T0.isoformat(),
        quality=QUALITY_LIVE,
        category="CREATOR",
    )
    assert atom["status"] == "UNKNOWN"
    assert atom["value"] is None
    assert atom["unknown_reason"]
    assert atom["quality"] == QUALITY_LIVE
    assert atom["calibrated_probability"] is False


def test_lifecycle_mapping():
    assert lifecycle_of(gate_decision="PASSED", investigation_status="WATCHING", quality_state="STABLE", outcome_label="UNKNOWN") == "WATCHING"
    assert lifecycle_of(gate_decision="PASSED", investigation_status="INVESTIGATING", quality_state="UNKNOWN", outcome_label="UNKNOWN") == "INVESTIGATING"
    assert lifecycle_of(gate_decision="PASSED", investigation_status="WATCHING", quality_state="STABLE", outcome_label="RUNNER") == "COMPLETED"
    assert lifecycle_of(gate_decision="REJECTED", investigation_status="REJECTED", quality_state=None, outcome_label=None) == "FAILED"
    assert lifecycle_of(gate_decision=None, investigation_status=None, quality_state=None, outcome_label=None) == "UNKNOWN"
    assert lifecycle_of(gate_decision="PASSED", investigation_status="WATCHING", quality_state=None, outcome_label=None, interrupted=True) == "INTERRUPTED"


def test_empty_store_is_empty():
    mem = IntelligenceMemory()
    out = assemble_investigation(mem, MINT, as_of=T0, quality=QUALITY_LIVE)
    assert out["empty"] is True
    assert out["lifecycle"] == "UNKNOWN"
    listed = list_investigations(mem, quality=QUALITY_LIVE)
    assert listed["count"] == 0
    assert listed["empty_note"] == "NO ACTIVE INVESTIGATIONS"


def test_as_of_hides_future_ticks():
    mem = IntelligenceMemory()
    rec = investigation_record(
        {"mint": MINT, "protocol": "pumpswap", "volume_usd": 172_000, "liquidity_usd": 40_000,
         "decision_timestamp": T0.isoformat()},
        gate1_passed=True,
        investigation_status="WATCHING",
    )
    mem.record_investigation(rec)
    mem.record_market_tick(mint=MINT, observed_at=T0, volume_m5_usd=172_000, price_usd=1.0)
    mem.record_market_tick(mint=MINT, observed_at=T0 + timedelta(seconds=1800), volume_m5_usd=900_000, price_usd=9.0)
    at0 = assemble_investigation(mem, MINT, as_of=T0, quality=QUALITY_LIVE)
    later = assemble_investigation(mem, MINT, as_of=T0 + timedelta(seconds=1800), quality=QUALITY_LIVE)
    slices0 = {s["offset_sec"]: s for s in at0["observations"]["slices"]}
    slicesL = {s["offset_sec"]: s for s in later["observations"]["slices"]}
    assert slices0[0]["volume_5m"] == 172_000
    assert slices0[1800]["volume_5m"] != 900_000
    assert slicesL[1800]["volume_5m"] == 900_000
    assert at0["investigation_id"] == later["investigation_id"]
    assert at0["calibrated_probability"] is False


def test_unknown_creator_is_not_low_risk():
    mem = IntelligenceMemory()
    rec = investigation_record(
        {"mint": MINT, "protocol": "pumpswap", "volume_usd": 172_000, "decision_timestamp": T0.isoformat(),
         "creator": None},
        gate1_passed=True,
        investigation_status="INVESTIGATING",
    )
    mem.record_investigation(rec)
    out = assemble_investigation(mem, MINT, as_of=T0)
    assert "creator" in out["unknowns"]
    creator_ev = next(e for e in out["evidence"] if e["signal"] == "creator")
    assert creator_ev["status"] == "UNKNOWN"
    assert creator_ev["value"] is None


def test_simulation_is_not_live_and_pipeline_connects():
    sim = run_simulation()
    assert sim["quality"] == QUALITY_SIMULATION
    assert sim["live_contaminated"] is False
    assert sim["t1800"]["quality"] == QUALITY_SIMULATION
    assert sim["t0"]["quality"] == QUALITY_SIMULATION
    assert sim["gate_eligible"] is True
    assert sim["gate1_usd"] == 150_000.0
    assert sim["investigation_id"]
    assert sim["t1800"]["investigation_id"] == sim["t0"]["investigation_id"]
    assert sim["t1800"]["links"]["token"].startswith("/tokens/")
    assert sim["future_hidden"] is True
    assert sim["calibrated_probability"] is False
    assert sim["t1800"]["gate"]["not_a_buy"] is True
    # outcome/memory/analogue/recipe all present as keys
    for key in ("evidence", "observations", "quality_state", "analogues", "recipe", "outcome", "unknowns"):
        assert key in sim["t1800"]


def test_duplicate_investigation_rejected():
    mem = IntelligenceMemory()
    rec = investigation_record(
        {"mint": MINT, "protocol": "pumpswap", "volume_usd": 172_000, "decision_timestamp": T0.isoformat()},
        gate1_passed=True,
        investigation_status="WATCHING",
    )
    assert mem.record_investigation(rec) is True
    rec2 = dict(rec)
    rec2["volume_5m_at_gate"] = 1
    assert mem.record_investigation(rec2) is False
    assert mem.investigations[0]["volume_5m_at_gate"] == 172_000


def test_health_probe_still_non_destructive():
    src = (ROOT / "packages/stinky-core/src/stinky_core/transport/redis_streams.py").read_text(encoding="utf-8")
    start = src.find("async def health_check")
    nxt = src.find("\n    async def ", start + 10)
    chunk = src[start:nxt]
    assert "self._reset" not in chunk


def test_no_atlas_in_coordination():
    src = (ROOT / "packages/stinky-core/src/stinky_core/coordination.py").read_text(encoding="utf-8")
    low = src.lower()
    assert "robinhood" not in low
    assert "atlas" not in low
    assert "paper trade" not in low
    assert "machine learning" not in low


def test_version_tag():
    assert COORDINATION_VERSION.startswith("intel-v2.0.0")
