from pathlib import Path
import importlib.util
P=Path(__file__).parents[1]/"scripts"/"run_intelligence_paper_decisions.py"
def module():
    spec=importlib.util.spec_from_file_location("paper",P); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
def test_policy_is_paper_only_and_neutral_point():
    m=module(); assert m.POLICY_VERSION=="genesis-evidence-paper-v1"; assert m.MIN_WOULD_ENTER_SCORE==50.0
    assert m.AUTHORITY["paper_only"] is True; assert m.AUTHORITY["live_execution"] is False
    assert m.AUTHORITY["trading_authority"] is False; assert m.AUTHORITY["trade_signal"] is False
def test_insufficient_never_enters():
    m=module(); assert m.decide({"status":"INSUFFICIENT","score":None})[0]=="NO_DECISION"
def test_neutral_point_is_pass_and_positive_edge_enters():
    m=module(); assert m.decide({"status":"KNOWN","score":50.0})[0]=="PAPER_PASS"
    assert m.decide({"status":"KNOWN","score":50.001})[0]=="PAPER_WOULD_ENTER"
    assert m.decide({"status":"KNOWN","score":49.999})[0]=="PAPER_PASS"
def test_query_is_prospective_idempotent_and_outcome_free():
    s=P.read_text(); assert "iss.migration_at >= $1" in s; assert "iss.scored_at >= $1" in s
    assert "ON CONFLICT(shadow_score_id,policy_version) DO NOTHING" in s
    assert "canonical_measured_outcome" not in s; assert "outcome_label" not in s; assert "--boundary" in s
