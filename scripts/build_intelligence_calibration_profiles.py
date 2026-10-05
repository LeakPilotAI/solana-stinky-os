#!/usr/bin/env python3
"""Build descriptive, evidence-only historical calibration profiles."""
from __future__ import annotations
import argparse,csv,json,math
from pathlib import Path
FEATURES=("price_usd","liquidity_usd","volume_m5_usd","market_cap_usd","early_buyer_count","meaningful_buyer_count","buyer_sol_spent")
LABELS=("RUNNER","HELD","FADE")
def num(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except (TypeError,ValueError): return None
def quantile(xs,p):
    xs=sorted(xs)
    if not xs:return None
    k=(len(xs)-1)*p; lo=math.floor(k); hi=math.ceil(k)
    return xs[lo] if lo==hi else xs[lo]*(hi-k)+xs[hi]*(k-lo)
def bucket_bounds(rows,feature):
    xs=[x for r in rows if (x:=num(r.get(feature))) is not None]
    return quantile(xs,1/3),quantile(xs,2/3)
def bucket_name(x,q1,q2):
    if x is None:return "UNKNOWN"
    if x<=q1:return "LOW"
    if x<=q2:return "MID"
    return "HIGH"
def profile(rows, feature):
    q1,q2=bucket_bounds(rows,feature); buckets={}
    for b in ("LOW","MID","HIGH","UNKNOWN"):
        rs=[r for r in rows if bucket_name(num(r.get(feature)),q1,q2)==b]
        counts={lab:sum(r["outcome_label"]==lab for r in rs) for lab in LABELS}; n=len(rs)
        buckets[b]={"n":n,"labels":counts,"rates":{lab:(counts[lab]/n if n else None) for lab in LABELS},
                    "adequate_for_directional_use": counts["RUNNER"]>=10 and counts["FADE"]>=10}
    return {"tertile_bounds":[q1,q2],"buckets":buckets}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("inputs",nargs="+",type=Path); ap.add_argument("--ledger",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); a=ap.parse_args()
    ledger=json.loads(a.ledger.read_text(encoding="utf-8"))
    allowed=[x["feature"] for x in ledger["features"] if x["decision"] in ("INCLUDE","WATCH") and x["feature"] in FEATURES]
    out={"profile_version":"historical-calibration-v1","authority":"evidence_only","trade_signal":False,"predictive_authority":False,
         "minimum_directional_sample":{"RUNNER":10,"FADE":10},"features":allowed,"horizons":{}}
    for path in a.inputs:
        rows=list(csv.DictReader(path.open(encoding="utf-8"))); h=str(int(rows[0]["horizon_sec"]))
        caps=[x for r in rows if (x:=num(r.get("market_cap_usd"))) is not None]; q1,q2=quantile(caps,1/3),quantile(caps,2/3)
        hr={"rows":len(rows),"labels":{lab:sum(r["outcome_label"]==lab for r in rows) for lab in LABELS},"market_cap_regimes":{}}
        regimes=(("low",None,q1),("mid",q1,q2),("high",q2,None))
        for name,lo,hi in regimes:
            def inside(r):
                x=num(r.get("market_cap_usd")); return x is not None and (lo is None or x>lo) and (hi is None or x<=hi)
            rs=[r for r in rows if inside(r)]
            counts={lab:sum(r["outcome_label"]==lab for r in rs) for lab in LABELS}
            hr["market_cap_regimes"][name]={"bounds":[lo,hi],"n":len(rs),"labels":counts,
                "adequate_for_directional_use":counts["RUNNER"]>=10 and counts["FADE"]>=10,
                "feature_profiles":{f:profile(rs,f) for f in allowed}}
        out["horizons"][h]=hr
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(out,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps({"output":str(a.output),"horizons":list(out["horizons"]),"features":allowed},sort_keys=True))
if __name__=="__main__": main()
