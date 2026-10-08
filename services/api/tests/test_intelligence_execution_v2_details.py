import asyncio
from datetime import datetime, timedelta, timezone
from copy import deepcopy
import pytest
from stinky_api import intelligence_execution_v2_details as d

T = datetime(2026, 10, 7, 11, 51, 36, 391317, tzinfo=timezone.utc)
REG = {"policy": d.v2.policy(), "policy_sha256": d.v2.policy_hash(d.v2.policy()), "prospective_boundary": T}


def row(status="PAPER_PRICED", ident=1):
    source = {"id": ident, "track_id": f"track-{ident}", "mint": f"mint-{ident}", "policy_version": "genesis-evidence-paper-v3",
              "decision": "PAPER_WOULD_ENTER", "migration_at": T, "scored_at": T, "decided_at": T}
    plan = d.v2.make_plan(source, T, T+timedelta(seconds=1))
    snapshots = [{"snapshot_id": f"snapshot-{phase}", "mint": source["mint"], "captured_at": d.v2.dt(plan[f"{phase}_target"])+timedelta(seconds=delay),
                  "price_usd": 10, "liquidity_usd": 2000 if status != "REJECTED" else 500}
                 for phase, delay in [("entry", 0), ("exit", 30)]]
    result = None if status == "PENDING" else d.v2.evaluate(plan, [] if status == "UNKNOWN" else snapshots, T+timedelta(seconds=125))
    return {"id": ident, "mint": source["mint"], "plan": plan, "plan_sha256": d.v2.policy_hash(plan), "result": result,
            "result_sha256": d.v2.policy_hash(result) if result else None, "recorded_at": T+timedelta(seconds=125) if result else None}


def test_bound_latency_exact_reasons_pending_and_no_mutation():
    rows = [row(s, i) for i, s in enumerate(["PAPER_PRICED", "UNKNOWN", "REJECTED", "PENDING"], 1)]
    before = deepcopy(rows)
    result = d.summarize_details(rows, REG, T+timedelta(seconds=500))
    assert result["counts"] == {"PAPER_PRICED": 1, "UNKNOWN": 1, "REJECTED": 1, "PENDING": 1}
    assert result["latency"]["entry_observation_delay"] == {"n": 1, "unavailable": 3, "median_sec": 0, "p90_sec": 0, "max_sec": 0}
    assert result["latency"]["exit_observation_delay"]["max_sec"] == 30
    assert result["latency"]["detection_to_admission"]["median_sec"] is None
    assert result["bound_observations"] == {"entry": 1, "exit": 1, "unavailable": 3}
    assert result["pending"] == {"awaiting_maturity": 0, "mature_without_result": 1}
    assert result["reasons"] == [{"status": "REJECTED", "reason": "entry_liquidity_below_frozen_minimum", "count": 1},
                                 {"status": "UNKNOWN", "reason": "entry_observation_missing", "count": 1}]
    assert rows == before and "adequacy_status" not in result
    assert len(result["missing_windows"]) == 1  # Rejected is not reclassified.


def test_empty_evidence_and_pending_boundary():
    empty = d.summarize_details([], REG, T)
    assert empty["freshness"]["bound_exit"]["age_sec"] is None
    assert empty["latency"]["entry_observation_delay"]["n"] == 0
    p = row("PENDING")
    assert d.summarize_details([p], REG, T+timedelta(seconds=119))["pending"]["awaiting_maturity"] == 1
    assert d.summarize_details([p], REG, T+timedelta(seconds=120))["pending"]["mature_without_result"] == 1


def test_p90_is_nearest_rank_and_empty_is_unavailable():
    assert d.distribution(list(range(1, 11)), 13) == {"n": 10, "unavailable": 3, "median_sec": 5.5, "p90_sec": 9, "max_sec": 10}
    assert d.distribution([], 3)["p90_sec"] is None


@pytest.mark.parametrize("defect", ["hash", "authority", "boundary", "record_clock", "schedule"])
def test_malformed_or_unsafe_evidence_is_rejected(defect):
    r = row("PENDING" if defect in {"authority", "schedule"} else "PAPER_PRICED")
    if defect == "hash": r["plan_sha256"] = "bad"
    if defect == "authority": r["plan"]["live_execution"] = True
    if defect == "boundary": r["plan"]["prospective_boundary"] = (T-timedelta(seconds=1)).isoformat()
    if defect == "record_clock": r["recorded_at"] += timedelta(seconds=1)
    if defect == "schedule": r["plan"]["exit_target"] = (T+timedelta(seconds=89)).isoformat()
    if defect in {"authority", "boundary", "schedule"}: r["plan_sha256"] = d.v2.policy_hash(r["plan"])
    with pytest.raises(ValueError): d.summarize_details([r], REG, T+timedelta(seconds=500))


class Result:
    def __init__(self, value): self.value = value
    def mappings(self): return self
    def all(self): return self.value
    def one(self): return self.value
    def scalar_one(self): return self.value


class Session:
    def __init__(self, rows=(), fail=False): self.rows, self.fail, self.queries, self.rolled_back = list(rows), fail, [], False
    async def execute(self, query, params=None):
        sql = str(query)
        self.queries.append((sql, params))
        if self.fail: raise OSError("SECRET_DB_URI")
        if "clock_timestamp" in sql: return Result(T+timedelta(seconds=500))
        if "SELECT * FROM intelligence_execution_v2_registry" in sql: return Result(REG)
        if "SELECT p.id" in sql: return Result(self.rows)
        if "SELECT max" in sql: return Result(None)
        return Result([])
    async def rollback(self): self.rolled_back = True


def local_unavailable(*args):
    return {"collector": {"timestamped_events": [], "status": "UNAVAILABLE"}}, {"collector": {"status": "UNAVAILABLE"}}


def test_operator_select_bounds_and_disconnected_logs(monkeypatch):
    monkeypatch.setattr(d, "local_support", local_unavailable)
    s = Session([row("UNKNOWN")])
    result = asyncio.run(d.operator_details(s))
    assert result["status"] == "OBSERVED" and result["rate_limit_correlations"][0]["rate_limit_lines"] is None
    assert result["collection"]["heartbeats"]["collector"]["status"] == "UNAVAILABLE"
    assert s.queries[0][0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    assert any(params and params.get("limit") == 501 for _, params in s.queries)
    assert any("LIMIT 101" in sql for sql, _ in s.queries)
    assert all(sql.startswith(("SELECT", "SET")) for sql, _ in s.queries)


def test_failure_returns_no_metrics_or_credentials():
    s = Session(fail=True)
    result = asyncio.run(d.operator_details(s))
    assert result["status"] == "UNAVAILABLE" and "counts" not in result and "SECRET" not in str(result) and s.rolled_back


def test_plan_and_source_coverage_caps_are_explicit(monkeypatch):
    monkeypatch.setattr(d, "local_support", local_unavailable)
    rows = [row("UNKNOWN", n) for n in range(501)]
    result = asyncio.run(d.operator_details(Session(rows)))
    assert result["scope"] == {"sampled_plans": 500, "plan_limit": 500, "truncated": True, "selection": "LATEST_PLAN_IDS"}
    assert result["missing_windows_truncated"] and len(result["source_coverage"]) == 20
    assert result["counts"]["UNKNOWN"] == 500


def test_one_log_outside_window_cannot_manufacture_zero_correlation(monkeypatch):
    def partial(*args):
        return {"collector": {"timestamped_events": [], "earliest_timestamp": (T+timedelta(seconds=300)).isoformat(),
                              "latest_timestamp": (T+timedelta(seconds=500)).isoformat()},
                "maintain": {"timestamped_events": [], "earliest_timestamp": T.isoformat(),
                             "latest_timestamp": (T+timedelta(seconds=500)).isoformat()}}, {}
    monkeypatch.setattr(d, "local_support", partial)
    out = asyncio.run(d.operator_details(Session([row("UNKNOWN")])))
    assert out["rate_limit_correlations"] == [{"plan_id": 1, "rate_limit_lines": None, "retained_window_covered": False, "causal": False}]
