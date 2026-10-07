from pathlib import Path
import importlib.util
P=Path(__file__).parents[1]/"scripts"/"summarize_intelligence_paper_execution.py"
def mod():
 spec=importlib.util.spec_from_file_location("s",P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def test_gate_stays_collection_below_minimum():
 m=mod();x=m.summarize({"results":[{"status":"PENDING"}]*4})
 assert x["status"]=="COLLECTION_MODE" and x["live_trading_authority"] is False
def test_gate_requires_matured_filled_and_fill_quality():
 m=mod()
 good=[{"status":"FILLED","net_multiple":1.1} for _ in range(20)]
 no=[{"status":"NO_FILL"} for _ in range(10)]
 x=m.summarize({"results":good+no})
 assert x["status"]=="EVALUATE" and x["matured"]==30 and x["filled"]==20
def test_gate_rejects_excess_no_fill_and_reports_uncertainty():
 m=mod()
 fills=[{"status":"FILLED","net_multiple":1.2} for _ in range(20)]
 no=[{"status":"NO_FILL"} for _ in range(21)]
 x=m.summarize({"results":fills+no})
 assert x["status"]=="COLLECTION_MODE" and x["no_fill_rate"]>.5
 assert x["win_rate"]["ci95"][0] < x["win_rate"]["rate"] <= x["win_rate"]["ci95"][1]
def test_frozen_minimums():
 m=mod();assert (m.MIN_MATURED,m.MIN_FILLED,m.MAX_NO_FILL_RATE)==(30,20,.50)
