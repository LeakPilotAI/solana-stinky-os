from datetime import datetime,timezone,timedelta
from pathlib import Path
import importlib.util
P=Path(__file__).parents[1]/"scripts"/"analyze_intelligence_prospective_robustness.py"
def mod():
 spec=importlib.util.spec_from_file_location("rob",P); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
def row(decision,label,peak,ep=1e-6,liq=5000):
 now=datetime.now(timezone.utc)
 return {"decision":decision,"decided_at":now,"completed_at":now+timedelta(hours=1),
 "score_payload":{"regime":"mid","score":55},"outcome":{"label":label,"peak_multiple":peak,"entry_price_usd":ep,"final_liquidity_usd":liq}}
def test_robustness_keeps_authority_off_and_threshold_frozen():
 m=mod(); x=m.summarize([row("PAPER_WOULD_ENTER","RUNNER",2),row("PAPER_PASS","FADE",1)])
 assert x["live_trading_authority"] is False and x["threshold_retuning_permitted"] is False
def test_plausibility_screen_is_diagnostic_and_excludes_tiny_entry():
 m=mod(); rows=[row("PAPER_PASS","RUNNER",1000,ep=1e-10,liq=10),row("PAPER_PASS","FADE",1)]
 x=m.summarize(rows)
 assert x["raw"]["PAPER_PASS"]["n"]==2
 assert x["plausibility_screened"]["PAPER_PASS"]["n"]==1
 assert "not a trading/admission rule" in x["diagnostic_plausibility_screen"]["note"]
def test_wilson_and_two_proportion_report_uncertainty():
 m=mod(); w=m.wilson(15,27); c=m.two_prop(15,27,13,40)
 assert 0<w["ci95"][0]<w["rate"]<w["ci95"][1]<1
 assert c["difference"]>0 and 0<=c["p_two_sided"]<=1
