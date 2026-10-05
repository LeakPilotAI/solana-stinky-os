#!/usr/bin/env python3
"""Audit coverage/distributions for leakage-safe Genesis as-of datasets."""
from __future__ import annotations
import argparse,csv,json,math,statistics
from pathlib import Path
NUMERIC=("price_usd","liquidity_usd","volume_m5_usd","market_cap_usd","early_buyer_count","meaningful_buyer_count","buyer_sol_spent")
LABELS=("RUNNER","HELD","FADE")
def num(v):
    if v in (None,""): return None
    try:
        x=float(v); return x if math.isfinite(x) else None
    except (TypeError,ValueError): return None
def quantile(xs,p):
    ys=sorted(xs)
    if not ys:return None
    k=(len(ys)-1)*p; lo=math.floor(k); hi=math.ceil(k)
    return ys[lo] if lo==hi else ys[lo]*(hi-k)+ys[hi]*(k-lo)
def summary(xs): return {"n":len(xs),"median":statistics.median(xs) if xs else None,"q1":quantile(xs,.25),"q3":quantile(xs,.75)}
def cliffs(a,b):
    if not a or not b:return None
    return (sum(x>y for x in a for y in b)-sum(x<y for x in a for y in b))/(len(a)*len(b))
def effect(rows,f):
    a=[x for r in rows if r["outcome_label"]=="RUNNER" and (x:=num(r.get(f))) is not None]
    b=[x for r in rows if r["outcome_label"]=="FADE" and (x:=num(r.get(f))) is not None]
    return {"cliffs_delta":cliffs(a,b),"runner":summary(a),"fade":summary(b)}
def audit(paths):
    out={"audit_version":"asof-feature-audit-v1","horizons":{}}
    for path in paths:
        rows=list(csv.DictReader(path.open(encoding="utf-8"))); h=int(rows[0]["horizon_sec"]); hr={"rows":len(rows),"labels":{},"runner_vs_fade":{},"regimes":{}}
        for lab in LABELS:
            rs=[r for r in rows if r["outcome_label"]==lab]; ls={"n":len(rs),"features":{}}
            for f in NUMERIC:
                xs=[x for r in rs if (x:=num(r.get(f))) is not None]; ls["features"][f]={"coverage":len(xs)/len(rs) if rs else 0.0,**summary(xs)}
            hr["labels"][lab]=ls
        hr["runner_vs_fade"]={f:effect(rows,f) for f in NUMERIC}
        caps=[x for r in rows if (x:=num(r.get("market_cap_usd"))) is not None]; q1,q2=quantile(caps,1/3),quantile(caps,2/3)
        for name,lo,hi in (("low",None,q1),("mid",q1,q2),("high",q2,None)):
            def inside(r):
                x=num(r.get("market_cap_usd")); return x is not None and (lo is None or x>lo) and (hi is None or x<=hi)
            rs=[r for r in rows if inside(r)]
            hr["regimes"][name]={"market_cap_bounds":[lo,hi],"n":len(rs),"labels":{lab:sum(r["outcome_label"]==lab for r in rs) for lab in LABELS},"runner_vs_fade":{f:effect(rs,f) for f in NUMERIC}}
        out["horizons"][str(h)]=hr
    return out
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("inputs",nargs="+",type=Path); ap.add_argument("--output",type=Path,required=True); a=ap.parse_args(); report=audit(a.inputs); a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(report,indent=2,sort_keys=True),encoding="utf-8"); print(json.dumps({"output":str(a.output),"horizons":list(report["horizons"])},sort_keys=True))
if __name__=="__main__": main()
