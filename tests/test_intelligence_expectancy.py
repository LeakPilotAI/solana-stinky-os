from pathlib import Path
import importlib.util
from datetime import datetime,timezone,timedelta
P=Path(__file__).parents[1]/"scripts"/"evaluate_intelligence_expectancy.py"
def mod():
 spec=importlib.util.spec_from_file_location("ev",P); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
def row(decision,decided,outcome=None,completed=None):
 return {"decision":decision,"decided_at":decided,"outcome":outcome,"completed_at":completed}
def test_zero_matured_stays_collection_mode():
 m=mod(); now=datetime.now(timezone.utc); x=m.summarize([row("PAPER_WOULD_ENTER",now)],now)
 assert x["status"]=="COLLECTION_MODE" and x["matured"]==0 and x["threshold_retuning_permitted"] is False
def test_small_matured_sample_stays_collection_mode():
 m=mod(); now=datetime.now(timezone.utc); out={"label":"RUNNER","peak_multiple":2.0}
 x=m.summarize([row("PAPER_WOULD_ENTER",now,out,now+timedelta(hours=1))],now)
 assert x["status"]=="COLLECTION_MODE" and x["matured"]==1
def test_future_outcome_join_requires_decision_precede_completion():
 m=mod(); now=datetime.now(timezone.utc); out={"label":"FADE"}
 try:m.summarize([row("PAPER_PASS",now,out,now-timedelta(seconds=1))],now)
 except RuntimeError:return
 assert False
def test_policy_is_frozen_and_outcome_not_in_decision_source():
 m=mod(); s=P.read_text(); assert m.POLICY_VERSION=="genesis-evidence-paper-v2"; assert m.FROZEN_THRESHOLD==50.0
 assert m.MIN_MATURED_TOTAL==30 and m.MIN_MATURED_PER_DECISION==10
 assert "threshold_retuning_permitted" in s and "live_trading_authority" in s
