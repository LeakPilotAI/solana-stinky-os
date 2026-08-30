"""Operator observability. SIMULATION unless labeled otherwise.

Does not lower Gate 1. Does not invent a live $150k print.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DISCORD = Path(__file__).resolve().parents[3] / "services" / "discord-bot" / "src"
if str(DISCORD) not in sys.path:
    sys.path.insert(0, str(DISCORD))

from stinky_core.admission import GATE1_VOLUME_5M_USD, GATE1_VOLUME_CALIBRATION_MAX_USD, evaluate_gate1
from stinky_core.intelligence import INTEL_VERSION
from stinky_core.memory import IntelligenceMemory
from stinky_core.observation import investigation_record, watch_should_resume
from stinky_core.operator import (
    OPERATOR_VERSION,
    classify_delivery,
    classify_lifecycle,
    count_live_gate1,
    database_health,
    discord_status,
    evidence_label,
    export_investigation,
    investigation_card,
    last_observation_view,
    live_gate1_status,
    operator_desk,
    provider_health,
    quality_dip_trace,
    would_policy_fire,
)
from stinky_core.quality_state import evaluate_quality_state
from stinky_core.sqlstore import SqliteMemoryStore
from discord_bot.policy import should_alert

MINT = "OpMintAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAApump"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_gate1_still_150k():
    assert GATE1_VOLUME_5M_USD == 150_000
    assert GATE1_VOLUME_CALIBRATION_MAX_USD == 200_000
    assert INTEL_VERSION.startswith("intel-v1.11") or INTEL_VERSION.startswith("intel-v1.10")
    d = evaluate_gate1({"mint": MINT, "protocol": "pumpswap", "volume_usd": 150_000, "migrated": True})
    assert d.eligible is True
    d = evaluate_gate1({"mint": MINT, "protocol": "pumpswap", "volume_usd": 149_999, "migrated": True})
    assert d.eligible is False


def test_evidence_labels_do_not_mix():
    assert evidence_label("LIVE") == "LIVE"
    assert evidence_label("fixture") == "FIXTURE"
    assert evidence_label("SIMULATION") == "SIMULATION"
    assert evidence_label("MOCK") == "MOCK"
    assert evidence_label("made-up") == "UNKNOWN"


def test_live_gate1_status_never_fabricated():
    assert live_gate1_status(count=None) == "UNKNOWN"
    assert live_gate1_status(count=0) == "NOT OBSERVED"
    assert live_gate1_status(count=1) == "OBSERVED"
    assert live_gate1_status(count=None, explicit="NOT OBSERVED") == "NOT OBSERVED"


def test_lifecycle_path():
    assert classify_lifecycle(investigation=None, watch=None, later_tick_count=0, elapsed_sec=None, quality_state=None, active=False) == "UNKNOWN"
    assert classify_lifecycle(investigation=None, watch={"mint": MINT}, later_tick_count=0, elapsed_sec=10, quality_state=None, active=True) == "DETECTED"
    rec = {"mint": MINT}
    assert classify_lifecycle(investigation=rec, watch=None, later_tick_count=0, elapsed_sec=0, quality_state=None, active=True) == "QUALIFIED"
    assert classify_lifecycle(investigation=rec, watch=None, later_tick_count=0, elapsed_sec=5, quality_state=None, active=True) == "INVESTIGATING"
    assert classify_lifecycle(investigation=rec, watch=None, later_tick_count=3, elapsed_sec=120, quality_state="WATCH", active=True) == "WATCHING"
    assert classify_lifecycle(investigation=rec, watch=None, later_tick_count=6, elapsed_sec=1800, quality_state="STABLE", active=False) == "COMPLETED"
    assert classify_lifecycle(investigation=rec, watch=None, later_tick_count=0, elapsed_sec=1800, quality_state=None, active=False) == "INCOMPLETE"
    assert classify_lifecycle(investigation=rec, watch=None, later_tick_count=2, elapsed_sec=400, quality_state="FAILED", active=True) == "FAILED"
    assert classify_lifecycle(
        investigation=rec, watch=None, later_tick_count=2, elapsed_sec=400, quality_state="WATCH",
        active=False, live=True,
    ) == "INTERRUPTED"


def test_stale_watch_is_interrupted_not_healthy():
    rec = {"mint": MINT}
    st = classify_lifecycle(
        investigation=rec, watch={"mint": MINT, "status": "WATCHING"}, later_tick_count=2,
        elapsed_sec=400, quality_state="HEALTHY", active=False, last_observation_age_sec=200,
    )
    assert st == "INTERRUPTED"


def test_provider_down_is_not_a_quality_dip():
    mem = IntelligenceMemory()
    mem.record_investigation(investigation_record(
        {"mint": MINT, "protocol": "pumpswap", "volume_usd": 172_000, "liquidity_usd": 50_000, "decision_timestamp": T0.isoformat()},
        gate1_passed=True,
    ))
    mem.record_market_tick(mint=MINT, observed_at=T0, volume_m5_usd=172_000, liquidity_usd=50_000)
    mem.record_market_tick(mint=MINT, observed_at=T0 + timedelta(seconds=15), volume_m5_usd=170_000, liquidity_usd=49_000)
    mem.record_provider_probe({"provider": "dexscreener", "at": (T0 + timedelta(seconds=40)).isoformat(), "status": "DOWN", "ok": False, "error": "timeout"})
    st = evaluate_quality_state(mem, mint=MINT, t0=T0, as_of=T0 + timedelta(seconds=40))
    assert st["is_dip"] is False
    assert st["state"] != "FAILED"
    health = provider_health(mem.provider_probes, name="dexscreener")
    assert health["status"] == "DOWN"
    desk = operator_desk(mem, now=T0 + timedelta(seconds=40), evidence_label_default="SIMULATION")
    assert desk["providers"]["dexscreener"]["status"] == "DOWN"
    card = investigation_card(mem, mint=MINT, now=T0 + timedelta(seconds=15), evidence_label_default="SIMULATION")
    assert card["current_quality"] != "FAILED"
    assert card["evidence_label"] == "SIMULATION"
    assert desk["live_data_status"] == "DOWN"
    assert desk["quality_state"]["current"] != "FAILED" or desk["quality_state"]["current"] == "UNKNOWN"


def test_database_unknown_is_not_connected():
    h = database_health(connected=None)
    assert h["status"] == "UNKNOWN"
    down = database_health(connected=False, error="connection refused")
    assert down["status"] == "DOWN"
    up = database_health(connected=True, last_write_at=T0, last_read_at=T0)
    assert up["status"] == "CONNECTED"
    deg = database_health(connected=True, error="slow replica")
    assert deg["status"] == "DEGRADED"


def test_discord_policy_vs_delivery():
    spec = should_alert(mint=MINT, previous_state="HEALTHY", current_state="DETERIORATING", now=1.0)
    assert spec is not None
    assert would_policy_fire("HEALTHY", "DETERIORATING") is True
    silent = should_alert(mint=MINT, previous_state="WATCH", current_state="WATCH", now=1.0)
    assert silent is None
    fired = discord_status(policy_fired=True, delivery="NOT ATTEMPTED")
    assert fired["policy"] == "FIRED"
    assert fired["delivery"] == "NOT ATTEMPTED"
    sent = discord_status(policy_fired=True, delivery="SENT")
    assert sent["delivery"] == "SENT"
    failed = discord_status(policy_fired=True, delivery="FAILED", error="403")
    assert failed["delivery"] == "FAILED"
    assert classify_delivery(attempted=False, sent=0, failed=0) == "NOT ATTEMPTED"
    assert classify_delivery(attempted=True, sent=1, failed=0) == "SENT"
    assert classify_delivery(attempted=True, sent=0, failed=2) == "FAILED"
    assert classify_delivery(attempted=None) == "UNKNOWN"
    assert classify_delivery(attempted=True, sent=1, failed=3) == "SENT"


def test_simulation_watch_resume_and_export():
    """SIMULATION. Sqlite restart of watch state. Not a live Postgres restart."""
    mem = IntelligenceMemory()
    rec = investigation_record(
        {"mint": MINT, "protocol": "pumpswap", "volume_usd": 172_000, "liquidity_usd": 50_000,
         "decision_timestamp": T0.isoformat(), "pair_identifier": "pool1"},
        gate1_passed=True, investigation_status="INVESTIGATING",
    )
    rec["evidence_label"] = "SIMULATION"
    mem.record_investigation(rec)
    mem.record_market_tick(mint=MINT, observed_at=T0, volume_m5_usd=172_000, liquidity_usd=50_000)
    mem.record_market_tick(mint=MINT, observed_at=T0 + timedelta(seconds=15), volume_m5_usd=168_000, liquidity_usd=48_000)
    mem.record_market_tick(mint=MINT, observed_at=T0 + timedelta(seconds=120), volume_m5_usd=40_000, liquidity_usd=20_000, buys=2, sells=12, txns=14)
    q0 = evaluate_quality_state(mem, mint=MINT, t0=T0, as_of=T0 + timedelta(seconds=15))
    mem.record_quality_state(q0)
    q1 = evaluate_quality_state(mem, mint=MINT, t0=T0, as_of=T0 + timedelta(seconds=120), previous_state=q0["state"])
    mem.record_quality_state(q1)
    mem.record_watch_state({
        "mint": MINT, "started_at": T0.isoformat(), "last_observation_at": (T0 + timedelta(seconds=120)).isoformat(),
        "observation_count": 3, "status": "WATCHING", "resumed": False, "persistence_status": "WRITTEN",
        "evidence_label": "SIMULATION",
    })
    mem.record_operator_event({
        "mint": MINT, "at": T0.isoformat(), "kind": "gate1", "message": "Gate 1 qualified", "evidence_label": "SIMULATION",
    })
    mem.record_operator_event({
        "mint": MINT, "at": (T0 + timedelta(seconds=120)).isoformat(), "kind": "quality",
        "message": f"{q0['state']} → {q1['state']}", "evidence_label": "SIMULATION",
        "previous_state": q0["state"], "state": q1["state"],
    })
    mem.record_discord_delivery({
        "mint": MINT, "at": (T0 + timedelta(seconds=121)).isoformat(),
        "policy": "FIRED" if would_policy_fire(q0["state"], q1["state"]) else "NOT FIRED",
        "delivery": "NOT ATTEMPTED", "category": "WARNING", "error": None,
    })

    dips = quality_dip_trace(mem.quality_states)
    if q1["is_dip"]:
        assert dips
        assert dips[-1]["previous_state"] == q0["state"]
        assert dips[-1]["new_state"] == q1["state"]
        assert dips[-1]["timestamp"]
        assert "data_quality" in dips[-1]

    store = SqliteMemoryStore(":memory:")
    store.persist(mem)
    mem2 = store.load()
    assert any(w.get("mint") == MINT for w in mem2.watch_states)
    elapsed = 400.0
    assert watch_should_resume(elapsed_sec=elapsed, max_watch_sec=1800) is True
    mem2.record_watch_state({"mint": MINT, "resumed": True, "status": "WATCHING", "started_at": T0.isoformat()})
    card = investigation_card(mem2, mint=MINT, now=T0 + timedelta(seconds=120), evidence_label_default="SIMULATION")
    assert card["watch"]["resumed"] is True
    assert card["evidence_label"] == "SIMULATION"
    assert card["watch"]["resume_note"]
    exported = export_investigation(mem2, mint=MINT, now=T0 + timedelta(seconds=120), evidence_label_default="SIMULATION")
    assert exported["evidence_label"] == "SIMULATION"
    assert exported["discord"]["delivery"] == "NOT ATTEMPTED"
    assert exported["calibrated_probability"] is False
    assert exported["lifecycle"] in ("WATCHING", "INVESTIGATING", "QUALIFIED")
    assert "trace" in exported
    store2 = SqliteMemoryStore(":memory:")
    store2.persist(mem2)
    mem3 = store2.load()
    assert any(w.get("resumed") for w in mem3.watch_states if w.get("mint") == MINT)
    last = last_observation_view(mem)
    assert last["kind"] in ("market_tick", "quality", "gate1")
    assert last["at"]


def test_operator_desk_empty_is_empty():
    desk = operator_desk(IntelligenceMemory(), now=T0, evidence_label_default="SIMULATION")
    assert desk["investigations"] == []
    assert desk["database"]["status"] == "UNKNOWN"
    assert desk["providers"]["dexscreener"]["status"] == "UNKNOWN"
    assert desk["gate_status"]["threshold_usd"] == 150_000
    assert desk["gate_status"]["clamp_usd"] == 200_000
    assert desk["gate_status"]["live_gate1"] == "UNKNOWN"
    assert desk["last_observation"]["kind"] == "UNKNOWN"
    assert desk["next_observation"]["label"] == "NONE"
    assert desk["quality_state"]["current"] == "UNKNOWN"
    assert desk["discord"]["policy"] == "UNKNOWN"
    assert desk["discord"]["delivery"] == "UNKNOWN"
    assert desk["system_status"] == "IDLE"
    assert OPERATOR_VERSION.startswith("operator-v1")


def test_operator_desk_live_gate1_not_observed_when_probed_empty():
    desk = operator_desk(
        IntelligenceMemory(),
        now=T0,
        db={"connected": True, "last_read_at": T0, "last_write_at": T0},
        live_gate1_count=0,
    )
    assert desk["gate_status"]["live_gate1"] == "NOT OBSERVED"
    assert desk["database"]["status"] == "CONNECTED"
    assert count_live_gate1(IntelligenceMemory()) == 0


def test_unlabeled_investigation_is_not_live_gate1():
    mem = IntelligenceMemory()
    rec = investigation_record(
        {"mint": MINT, "protocol": "pumpswap", "volume_usd": 172_000, "decision_timestamp": T0.isoformat()},
        gate1_passed=True,
    )
    mem.record_investigation(rec)
    assert count_live_gate1(mem) == 0
    rec2 = dict(rec)
    rec2["mint"] = "LiveMintAAAAAAAAAAAAAAAAAAAAAAAAAAAApump"
    rec2["evidence_label"] = "LIVE"
    mem.record_investigation(rec2)
    mem.record_operator_event({
        "mint": rec2["mint"], "at": T0.isoformat(), "kind": "gate1",
        "message": "Gate 1 qualified", "evidence_label": "LIVE",
    })
    assert count_live_gate1(mem) == 1
