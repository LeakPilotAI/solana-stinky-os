#!/usr/bin/env python3
"""Summarize read-only prospective execution evidence with frozen adequacy gates."""
from __future__ import annotations
import argparse,json,math,subprocess,sys
from pathlib import Path
MIN_MATURED=30
MIN_FILLED=20
MAX_NO_FILL_RATE=.50
def wilson(k,n,z=1.96):
 if not n:return None
 p=k/n;den=1+z*z/n;c=(p+z*z/(2*n))/den
 h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
 return {"rate":p,"ci95":[c-h,c+h]}
def quantile(v,p):
 if not v:return None
 a=sorted(v);pos=(len(a)-1)*p;lo=int(pos);hi=min(lo+1,len(a)-1);f=pos-lo
 return a[lo]+(a[hi]-a[lo])*f
def summarize(report):
 rs=report["results"]; pending=sum(x["status"] in ("PENDING","PENDING_EXIT") for x in rs)
 mature=[x for x in rs if x["status"] in ("FILLED","NO_FILL")]
 fills=[x for x in mature if x["status"]=="FILLED"]; nofill=len(mature)-len(fills)
 vals=[float(x["net_multiple"]) for x in fills]; wins=sum(x>1 for x in vals)
 nofill_rate=nofill/len(mature) if mature else None
 adequate=len(mature)>=MIN_MATURED and len(fills)>=MIN_FILLED and nofill_rate<=MAX_NO_FILL_RATE
 return {"status":"EVALUATE" if adequate else "COLLECTION_MODE",
  "minimums":{"matured":MIN_MATURED,"filled":MIN_FILLED,"max_no_fill_rate":MAX_NO_FILL_RATE},
  "plans_total":len(rs),"pending":pending,"matured":len(mature),"filled":len(fills),"no_fill":nofill,
  "no_fill_rate":nofill_rate,"win_rate":wilson(wins,len(vals)),
  "net_multiple":{"mean":sum(vals)/len(vals) if vals else None,"median":quantile(vals,.5),
   "p25":quantile(vals,.25),"p75":quantile(vals,.75),"min":min(vals) if vals else None,"max":max(vals) if vals else None},
  "policy_retuning_permitted":False,"live_trading_authority":False}
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--report",required=True);ap.add_argument("--output");a=ap.parse_args()
 data=json.loads(Path(a.report).read_text(encoding="utf-8")); out=summarize(data)
 s=json.dumps(out,indent=2,sort_keys=True)
 if a.output:Path(a.output).write_text(s+"\n",encoding="utf-8")
 print(s)
if __name__=="__main__":main()
