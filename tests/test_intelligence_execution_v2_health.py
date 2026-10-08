import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import audit_intelligence_execution_v2_health as health

T = datetime(2026, 10, 8, tzinfo=timezone.utc)


@pytest.mark.parametrize("age,status", [(0, "RECENT"), (300, "RECENT"), (301, "STALE"), (-1, "CLOCK_INCONSISTENT")])
def test_freshness_boundary(age, status):
    assert health.freshness(T-timedelta(seconds=age), T, 300)["status"] == status


def test_missing_freshness_is_not_zero():
    assert health.freshness(None, T, 300) == {"status": "UNAVAILABLE", "age_sec": None, "latest_at": None}


def test_capture_gap_is_support_not_cause_or_ingestion():
    times = [T-timedelta(seconds=20), T+timedelta(seconds=45), T+timedelta(seconds=90)]
    out = health.window_support(times, T, T+timedelta(seconds=60))
    assert out["captured_in_window"] == 0
    assert out["bracketing_gap_sec"] == 65
    assert out["following_delay_sec"] == 45
    assert out["cause"] == "UNESTABLISHED" and out["ingestion_delay"] == "UNAVAILABLE"


def test_inclusive_frozen_window_and_unavailable_brackets():
    out = health.window_support([T, T+timedelta(seconds=30), T+timedelta(seconds=31)], T, T+timedelta(seconds=30))
    assert out["captured_in_window"] == 2
    assert out["following_capture"] is None and out["bracketing_gap_sec"] is None


@pytest.mark.parametrize("state,owned,status", [(None, False, "UNAVAILABLE"), ({}, True, "UNAVAILABLE"),
    ({"as_of": T.isoformat(), "service": "atlas"}, True, "UNAVAILABLE"),
    ({"as_of": T.isoformat(), "service": "collector"}, False, "UNVERIFIED_OR_STALE"),
    ({"as_of": (T-timedelta(seconds=181)).isoformat(), "service": "maintain"}, True, "UNVERIFIED_OR_STALE"),
    ({"as_of": T.isoformat(), "service": "collector"}, True, "OWNED_SUPERVISOR_PRESENT")])
def test_runtime_does_not_infer_app_health(state, owned, status):
    out = health.runtime_health(state, owned, T, 180)
    assert out["status"] == status
    assert out.get("application_health", "UNESTABLISHED") == "UNESTABLISHED"


def test_missingness_uses_terminals_and_preserves_rejected():
    rows = [{"result": {"status": s}, "recorded_at": T+timedelta(seconds=offset)}
            for s, offset in [("PAPER_PRICED", -1), ("UNKNOWN", 0), ("REJECTED", 1)]]
    rows.append({"result": None, "recorded_at": None})
    out = health.missingness_change(rows, T)
    assert out["before"]["terminal_rows"] == 1
    assert out["since"] == {"terminal_rows": 2, "unknown_rows": 1, "unknown_fraction": .5}
    assert out["increasing"] is True
    assert health.missingness_change([], T)["increasing"] is None


def test_disconnected_checkpoint_redacts_error_and_metrics():
    async def connect():
        raise OSError("postgresql://SECRET@secret-host")
    out = asyncio.run(health.checkpoint(connect))
    assert out["status"] == "UNAVAILABLE" and out["canonical"] is None
    assert "SECRET" not in str(out)


class Connection:
    def __init__(self, rows, monkeypatch):
        self.rows, self.closed, self.queries = rows, False, []
        monkeypatch.setattr(health.v2, "verify_registry", lambda r: {"prospective_boundary": T.isoformat()})

    def transaction(self, **kwargs):
        assert kwargs == {"isolation": "repeatable_read", "readonly": True}
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def fetchrow(self, query, *args):
        self.queries.append(query)
        return {"prospective_boundary": T}

    async def fetch(self, query, *args):
        self.queries.append(query)
        return [] if "market_snapshots" in query else self.rows

    async def fetchval(self, query, *args):
        self.queries.append(query)
        if "clock_timestamp" in query:
            return T+timedelta(seconds=300)
        if "pg_trigger" in query:
            return 6
        if "count(*)" in query:
            return 1
        return None

    async def close(self):
        self.closed = True


def test_empty_connected_snapshot_and_select_only(monkeypatch):
    conn = Connection([], monkeypatch)
    async def connect():
        return conn
    out = asyncio.run(health.checkpoint(connect))
    assert out["status"] == "OBSERVED" and out["canonical"]["distinct_mint_mature_plans"] == 0
    assert out["latest_market_capture"]["status"] == "UNAVAILABLE"
    assert out["latest_terminal_recording"]["age_sec"] is None
    assert out["worker_downtime"] == "UNESTABLISHED"
    assert all(q.lstrip().startswith("SELECT") for q in conn.queries) and conn.closed


def test_mature_missing_result_is_reported_not_terminal_or_session(monkeypatch):
    source = {"id": 1, "track_id": "track", "mint": "mint", "policy_version": "genesis-evidence-paper-v3",
              "decision": "PAPER_WOULD_ENTER", "migration_at": T, "scored_at": T, "decided_at": T}
    plan = health.v2.make_plan(source, T, T+timedelta(seconds=1))
    row = {"id": 1, "plan": plan, "plan_sha256": health.v2.policy_hash(plan),
           "result": None, "result_sha256": None, "recorded_at": None}
    conn = Connection([row], monkeypatch)
    out = asyncio.run(health.collect(conn))
    assert out["canonical"]["counts"] == {"PENDING": 1}
    assert out["canonical"]["verified_runtime_sessions"] == 0
    assert out["mature_without_result"] == [{"plan_id": 1, "overdue_sec": 180}]
    assert out["worker_downtime"] == "UNESTABLISHED"


def test_corrupt_evidence_fails_closed_and_closes_connection(monkeypatch):
    conn = Connection([{"plan": {}, "plan_sha256": "bad"}], monkeypatch)
    async def connect():
        return conn
    out = asyncio.run(health.checkpoint(connect))
    assert out["status"] == "UNAVAILABLE" and out["canonical"] is None and conn.closed


def test_bounded_logs_preserve_unavailable_clocks_and_redact(tmp_path):
    path = tmp_path / "maintain.log"
    payload = {"admitted": 0, "recorded": 0, **health.v2.AUTHORITY}
    path.write_text("SECRET-URL\n" + __import__("json").dumps(payload) +
                    "\n[2026-10-08T00:00:10Z] intelligence V2 capture error SECRET\n" +
                    "ConnectionResetError SECRET\n", encoding="utf-8")
    out = health.log_support(path, T)
    assert out["v2_success_lines"] == 1 and out["v2_success_timestamps"] == "UNAVAILABLE"
    assert out["category_line_counts"] == {"v2_capture_error": 1, "connection_reset": 1}
    assert out["timestamped_events"] == [{"category": "v2_capture_error", "at": "2026-10-08T00:00:10+00:00"}]
    assert "SECRET" not in str(out)
    assert health.log_support(path, T, 20)["tail_truncated"] is True
    assert health.log_support(tmp_path / "absent", T)["v2_success_lines"] is None
    rows = [{"current_capture_support": {"target": T.isoformat(), "window_end": (T+timedelta(seconds=30)).isoformat()}}]
    health.correlate_logs(rows, {"maintain": out})
    assert len(rows[0]["coincident_log_events"]) == 1 and rows[0]["log_cause"] == "UNESTABLISHED"


def test_rate_limit_requires_error_evidence_not_arbitrary_numbers(tmp_path):
    path = tmp_path / "collector.log"
    path.write_text("2026-10-08T00:00:00Z price=429 liquidity=4290\n"
                    "2026-10-08T00:00:01Z HTTP/1.1 429 Too Many Requests\n", encoding="utf-8")
    out = health.log_support(path, T)
    assert out["category_line_counts"] == {"provider_rate_limit": 1}
