from pathlib import Path
import importlib.util
P=Path(__file__).parents[1]/"scripts"/"simulate_intelligence_execution.py"
def mod():
 spec=importlib.util.spec_from_file_location("sim",P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def test_scenarios_are_fixed_and_conservative():
 m=mod(); assert [x["hold_sec"] for x in m.SCENARIOS]==[900,1800,3600]
 assert [x["cost_pct"] for x in m.SCENARIOS]==[.01,.02,.03]
 assert [x["latency_sec"] for x in m.SCENARIOS]==[15,30,30]
def test_summary_uses_fixed_horizon_multiple_not_peak():
 m=mod(); x=m.summarize([.5,1,2,4])
 assert x["n"]==4 and x["win_rate"]==.5 and x["median_multiple"]==1.5
def test_source_contract_keeps_authority_off():
 s=P.read_text()
 assert '"live_trading_authority":False' in s
 assert '"threshold_retuning_permitted":False' in s
 assert "not optimized" in s
