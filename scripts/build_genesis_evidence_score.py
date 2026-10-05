#!/usr/bin/env python3
"""Transparent evidence-only Genesis score from historical calibration."""
from __future__ import annotations
import argparse,csv,json,math
from pathlib import Path
SCORE_VERSION="genesis-evidence-score-v1"
HORIZON="60"
COMPONENTS=("liquidity_usd","volume_m5_usd","early_buyer_count","meaningful_buyer_count")
def num(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except (TypeError,ValueError): return None
def bucket(x,bounds):
    if x is None:return "UNKNOWN"
    q1,q2=bounds
    if x<=q1:return "LOW"
    if x<=q2:return "MID"
    return "HIGH"
def regime(cap,regs):
    if cap is None:return None
    for name in ("low","mid","high"):
        lo,hi=regs[name]["bounds"]
        if (lo is None or cap>lo) and (hi is None or cap<=hi): return name
    return None
def evidence(profile,value):
    b=bucket(value,profile["tertile_bounds"])
    if b=="UNKNOWN": return {"status":"UNKNOWN","bucket":b,"reason":"feature_missing"}
    cell=profile["buckets"][b]
    # Regime adequacy is the hard authority gate. Bucket evidence is descriptive
    # with an explicit minimum total sample so it can vary without pretending
    # each tertile independently satisfies the regime-level 10/10 contract.
    if cell["n"] < 7:
        return {"status":"INSUFFICIENT","bucket":b,"n":cell["n"],"reason":"bucket_total_sample_below_7"}
    rr=cell["rates"]["RUNNER"]; fr=cell["rates"]["FADE"]
    return {"status":"KNOWN","bucket":b,"n":cell["n"],"runner_rate":rr,"fade_rate":fr,"edge":rr-fr}
def score_row(row,cal):
    regs=cal["horizons"][HORIZON]["market_cap_regimes"]
    r=regime(num(row.get("market_cap_usd")),regs)
    out={"score_version":SCORE_VERSION,"authority":"evidence_only","trade_signal":False,
         "predictive_authority":False,"horizon_sec":60,"regime":r,"score":None,
         "status":"INSUFFICIENT","components":[],"redundancy_policy":"market_cap_selects_regime; price_and_market_cap_not_scored"}
    if r is None: out["reason"]="market_cap_missing"; return out
    rp=regs[r]
    if not rp["adequate_for_directional_use"]:
        out["reason"]="regime_sample_gate"; out["regime_labels"]=rp["labels"]; return out
    known=[]
    for f in COMPONENTS:
        ev=evidence(rp["feature_profiles"][f],num(row.get(f))); ev["feature"]=f
        if f in ("early_buyer_count","meaningful_buyer_count") and row.get(f) in ("",None):
            ev={"feature":f,"status":"UNKNOWN","reason":"buyer_missingness_UNKNOWN_not_negative"}
        out["components"].append(ev)
        if ev["status"]=="KNOWN": known.append(ev["edge"])
    if not known: out["reason"]="no_adequately_calibrated_components"; return out
    out["score"]=round(50.0+50.0*(sum(known)/len(known)),3)
    out["status"]="KNOWN"; out["known_components"]=len(known); out["reason"]="descriptive_calibrated_evidence"
    return out
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("dataset",type=Path); ap.add_argument("--calibration",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); a=ap.parse_args()
    cal=json.loads(a.calibration.read_text(encoding="utf-8")); rows=list(csv.DictReader(a.dataset.open(encoding="utf-8"))); scored=[]
    for row in rows:
        s=score_row(row,cal); s["mint"]=row.get("mint"); s["observed_outcome"]=row.get("outcome_label"); scored.append(s)
    payload={"score_version":SCORE_VERSION,"authority":"evidence_only","trade_signal":False,"predictive_authority":False,"rows":scored}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(payload,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps({"rows":len(scored),"known":sum(x["status"]=="KNOWN" for x in scored),"insufficient":sum(x["status"]=="INSUFFICIENT" for x in scored),"output":str(a.output)},sort_keys=True))
if __name__=="__main__": main()
