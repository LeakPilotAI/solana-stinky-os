from pathlib import Path
import importlib.util
P=Path(__file__).parents[1]/"scripts"/"report_intelligence_paper_execution.py"
def mod():
 spec=importlib.util.spec_from_file_location("r",P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def test_report_matches_frozen_policy():
 m=mod()
 assert (m.ENTRY_LATENCY,m.HOLD,m.COST,m.MIN_LIQ)==(30,900,.02,1000.0)
 assert m.POLICY=="genesis-paper-execution-v1"
def test_report_is_read_only_and_keeps_authority_off():
 s=P.read_text().lower()
 assert "insert into" not in s and "update " not in s and "delete from" not in s
 assert '"read_only":true' in s
 assert '"live_trading_authority":false' in s
 assert '"policy_retuning_permitted":false' in s
