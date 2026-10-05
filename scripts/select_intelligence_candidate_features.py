#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
FEATURES=("price_usd","liquidity_usd","volume_m5_usd","market_cap_usd","early_buyer_count","meaningful_buyer_count","buyer_sol_spent")
REGIMES=("low","mid","high")
def sign(x): return 0 if x is None or abs(x)<0.10 else (1 if x>0 else -1)
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("audit",type=Path); ap.add_argument("--output",type=Path,required=True); a=ap.parse_args()
    d=json.loads(a.audit.read_text(encoding="utf-8")); h60=d["horizons"]["60"]; h120=d["horizons"]["120"]; ledger=[]
    for f in FEATURES:
        coverage=min(h60["labels"][lab]["features"][f]["coverage"] for lab in ("RUNNER","FADE")); per={}; stable=0; eligible=0
        for reg in REGIMES:
            x=h60["regimes"][reg]; y=h120["regimes"][reg]; d60=x["runner_vs_fade"][f]["cliffs_delta"]; d120=y["runner_vs_fade"][f]["cliffs_delta"]; rn=x["labels"]["RUNNER"]; fn=x["labels"]["FADE"]
            enough=rn>=10 and fn>=10; same=sign(d60)!=0 and sign(d60)==sign(d120)
            eligible+=int(enough); stable+=int(enough and same)
            per[reg]={"runner_n":rn,"fade_n":fn,"delta_t60":d60,"delta_t120":d120,"adequate_sample":enough,"stable_direction":same}
        if coverage < .50: decision,reason="INSUFFICIENT","coverage_below_50pct"
        elif stable>=2: decision,reason="INCLUDE","adequate_coverage_and_stable_in_two_regimes"
        elif stable>=1: decision,reason="WATCH","stable_in_one_adequately_sampled_regime"
        else: decision,reason="INSUFFICIENT","no_stable_adequately_sampled_regime"
        item={"feature":f,"decision":decision,"reason":reason,"runner_fade_min_coverage_t60":coverage,"stable_regimes":stable,"eligible_regimes":eligible,"regimes":per}
        if f in ("price_usd","market_cap_usd"):
            item["redundancy_group"]="price_market_cap"
            item["constraint"]="do_not_double_weight"
        if f in ("early_buyer_count","meaningful_buyer_count","buyer_sol_spent"):
            item["missingness_policy"]="UNKNOWN_not_negative"
        ledger.append(item)
    ledger += [
        {"feature":"creator_prior_history","decision":"INSUFFICIENT","reason":"0pct_pre_migration_coverage_current_labels"},
        {"feature":"market_observations_txn_structure","decision":"INSUFFICIENT","reason":"collection_path_bias_0pct_runner_t60"},
        {"feature":"quality_state","decision":"INSUFFICIENT","reason":"collection_path_bias_0pct_runner_t60"}]
    out={"ledger_version":"candidate-feature-ledger-v1","default_horizon_sec":60,"features":ledger}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(out,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps({x["feature"]:x["decision"] for x in ledger},sort_keys=True))
if __name__=="__main__": main()
