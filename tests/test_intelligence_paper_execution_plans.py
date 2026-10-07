from pathlib import Path
import importlib.util
P=Path(__file__).parents[1]/"scripts"/"run_intelligence_paper_execution_plans.py"
def mod():
 spec=importlib.util.spec_from_file_location("pep",P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def test_execution_policy_is_frozen_and_paper_only():
 m=mod(); p=m.frozen_plan()
 assert m.POLICY_VERSION=="genesis-paper-execution-v1"
 assert p["entry"]=={"latency_sec":30,"min_liquidity_usd":1000.0}
 assert p["exit"]=={"type":"fixed_time","max_hold_sec":900}
 assert p["cost_model"]["round_trip_cost_pct"]==.02
 assert m.AUTHORITY["live_execution"] is False and m.AUTHORITY["trading_authority"] is False
def test_query_requires_future_incomplete_v3_enter_only():
 s=P.read_text()
 assert "d.policy_version=$1 AND d.decision='PAPER_WOULD_ENTER'" in s
 assert "d.decided_at >= $2 AND mt.completed_at IS NULL" in s
 assert "UNIQUE(paper_decision_id,execution_policy_version)" in s
def test_plan_has_no_outcome_dependent_exit():
 m=mod(); p=m.frozen_plan()
 assert p["exit"]["type"]=="fixed_time"
 assert "profit" not in str(p).lower() and "stop" not in str(p).lower()
 assert "no outcome-dependent tuning" in p["note"]
