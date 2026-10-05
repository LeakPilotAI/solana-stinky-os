#!/usr/bin/env python3
"""Export leakage-safe research rows through Docker-local psql."""
from __future__ import annotations
import argparse, csv, json, subprocess
from pathlib import Path
from export_intelligence_asof_dataset import DATASET_VERSION, FEATURE_COLUMNS, QUERY

def docker_rows(horizon_sec: int, container: str) -> list[dict]:
    sql = QUERY.replace("$1", str(int(horizon_sec)))
    wrapped = "COPY (" + sql.strip().rstrip(";") + ") TO STDOUT WITH (FORMAT CSV, HEADER TRUE)"
    cp = subprocess.run(
        ["docker","exec","-i",container,"psql","-U","stinky","-d","stinky","-v","ON_ERROR_STOP=1","-c",wrapped],
        text=True,capture_output=True,timeout=60,check=True,
    )
    rows=list(csv.DictReader(cp.stdout.splitlines()))
    for row in rows:
        raw=row.pop("outcome")
        outcome=json.loads(raw) if raw else {}
        row["dataset_version"]=DATASET_VERSION
        row["horizon_sec"]=horizon_sec
        row["feature_columns"]=list(FEATURE_COLUMNS)
        row["outcome_label"]=outcome.get("label")
        row["outcome_peak_multiple"]=outcome.get("peak_multiple")
        row["outcome_label_version"]=outcome.get("label_version")
        row["outcome_evidence_only"]=outcome.get("evidence_only")
        row["outcome_trade_signal"]=outcome.get("trade_signal")
        row["outcome_predictive_authority"]=outcome.get("predictive_authority")
    return rows

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--horizon-sec",type=int,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--container",default="stinky-postgres")
    a=ap.parse_args()
    rows=docker_rows(a.horizon_sec,a.container)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    fields=list(rows[0]) if rows else []
    with a.output.open("w",newline="",encoding="utf-8") as fh:
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader()
        for row in rows:
            w.writerow({k:json.dumps(v,sort_keys=True) if isinstance(v,(dict,list)) else v for k,v in row.items()})
    labels={}
    for row in rows: labels[row.get("outcome_label") or "UNKNOWN"]=labels.get(row.get("outcome_label") or "UNKNOWN",0)+1
    print(json.dumps({"transport":"docker-local-psql","horizon_sec":a.horizon_sec,"rows":len(rows),"labels":labels,"output":str(a.output)},sort_keys=True))
    return 0
if __name__=="__main__": raise SystemExit(main())
