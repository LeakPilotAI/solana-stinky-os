"""API/docs contracts for intel-v2.0 coordination. No live services."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def test_api_exposes_coordination_routes():
    t = read("services/api/src/stinky_api/main.py")
    assert '"/v1/coordination"' in t
    assert '"/v1/coordination/{mint}"' in t
    assert "assemble_investigation" in t
    assert "list_investigations" in t
    assert "intel-v2.0.0-coordination" in t


def test_cc_synthesis_does_not_hydrate_book_in_poll():
    t = read("services/api/src/stinky_api/main.py")
    # command_center synthesis is from already-fetched alerts, not _book_memory
    start = t.find("async def command_center")
    end = t.find("@app.get(\"/v1/coordination\")")
    chunk = t[start:end]
    assert "_book_memory" not in chunk
    assert '"synthesis"' in chunk


def test_gate1_untouched():
    t = read("packages/stinky-core/src/stinky_core/admission.py")
    assert "GATE1_VOLUME_5M_USD = 150_000.0" in t
    assert "GATE1_VOLUME_CALIBRATION_MAX_USD = 200_000.0" in t


def test_health_still_non_destructive():
    t = read("packages/stinky-core/src/stinky_core/transport/redis_streams.py")
    start = t.find("async def health_check")
    nxt = t.find("\n    async def ", start + 10)
    assert "self._reset" not in t[start:nxt]


def test_no_trading_in_coordination_module():
    t = read("packages/stinky-core/src/stinky_core/coordination.py").lower()
    assert "private key" not in t
    assert "paper trade" not in t
    assert "robinhood" not in t
