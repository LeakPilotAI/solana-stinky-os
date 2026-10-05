import importlib.util,json
from pathlib import Path
ROOT=Path(__file__).parents[1]
P=ROOT/"scripts"/"build_genesis_evidence_score.py"
def load():
    s=importlib.util.spec_from_file_location("ges",P); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
def calibration(adequate=True):
    cell={"n":20,"labels":{"RUNNER":12,"HELD":0,"FADE":8},"rates":{"RUNNER":.6,"HELD":0,"FADE":.4},"adequate_for_directional_use":True}
    fp={"tertile_bounds":[10,20],"buckets":{"LOW":cell,"MID":cell,"HIGH":cell,"UNKNOWN":{"n":0,"labels":{},"rates":{},"adequate_for_directional_use":False}}}
    reg={"bounds":[None,100],"n":20,"labels":{"RUNNER":12,"HELD":0,"FADE":8},"adequate_for_directional_use":adequate,"feature_profiles":{f:fp for f in ("liquidity_usd","volume_m5_usd","early_buyer_count","meaningful_buyer_count")}}
    return {"horizons":{"60":{"market_cap_regimes":{"low":reg,"mid":dict(reg,bounds=[100,200]),"high":dict(reg,bounds=[200,None],adequate_for_directional_use=False)}}}}
def test_score_is_evidence_only_and_no_price_marketcap_double_weight():
    m=load(); r=m.score_row({"market_cap_usd":"50","liquidity_usd":"15","volume_m5_usd":"15","early_buyer_count":"15","meaningful_buyer_count":"15"},calibration())
    assert r["status"]=="KNOWN" and r["score"]==60.0
    assert r["trade_signal"] is False and r["predictive_authority"] is False
    assert {x["feature"] for x in r["components"]}==set(m.COMPONENTS)
    assert "price_usd" not in m.COMPONENTS and "market_cap_usd" not in m.COMPONENTS
def test_high_regime_is_insufficient():
    m=load(); r=m.score_row({"market_cap_usd":"250"},calibration())
    assert r["status"]=="INSUFFICIENT" and r["reason"]=="regime_sample_gate" and r["score"] is None
def test_missing_buyer_is_unknown_not_negative():
    m=load(); r=m.score_row({"market_cap_usd":"50","liquidity_usd":"15","volume_m5_usd":"15","early_buyer_count":"","meaningful_buyer_count":""},calibration())
    buyers=[x for x in r["components"] if x["feature"] in ("early_buyer_count","meaningful_buyer_count")]
    assert all(x["status"]=="UNKNOWN" for x in buyers)

def test_outcome_label_cannot_change_score():
    m=load(); base={"market_cap_usd":"50","liquidity_usd":"15","volume_m5_usd":"15","early_buyer_count":"15","meaningful_buyer_count":"15"}
    runner=m.score_row(dict(base,outcome_label="RUNNER"),calibration())
    fade=m.score_row(dict(base,outcome_label="FADE"),calibration())
    assert runner==fade
