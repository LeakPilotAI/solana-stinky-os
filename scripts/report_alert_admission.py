"""Report why live Gate-1 investigations are or are not becoming alert candidates."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api" / "src"))

from stinky_api.alert_admission_audit import audit_alert_admission
from stinky_api.db import SessionLocal


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Read-only Genesis alert admission audit.")
    p.add_argument("--hours", required=True, type=float, help="Explicit lookback window in hours.")
    return p


async def run(args: argparse.Namespace) -> int:
    async with SessionLocal() as session:
        result = await audit_alert_admission(session, hours=args.hours)
    print("GENESIS ALERT ADMISSION AUDIT")
    print(f"Status: {result.get('status')}")
    print(f"Interpretation: {result.get('interpretation', 'UNKNOWN')}")
    events = result.get("events") or {}
    print(
        "Funnel: migrated={token_migrated} gate1={gate1_passed} inspections={deep_inspection_completed} "
        "alerts={alert_candidate} tracking_started={tracking_started} tracking_completed={tracking_completed}".format(**{
            "token_migrated": events.get("token_migrated", 0),
            "gate1_passed": events.get("gate1_passed", 0),
            "deep_inspection_completed": events.get("deep_inspection_completed", 0),
            "alert_candidate": events.get("alert_candidate", 0),
            "tracking_started": events.get("tracking_started", 0),
            "tracking_completed": events.get("tracking_completed", 0),
        })
    )
    print(f"Inspections: {result.get('inspection_count', 0)}")
    print(f"Has intelligence: {result.get('has_intelligence_count', 0)}")
    print(f"Alert OK: {result.get('alert_ok_count', 0)}")
    print("Alert reasons: " + json.dumps(result.get("alert_reasons") or {}, sort_keys=True))
    print("Missing fields: " + json.dumps(result.get("missing_fields") or {}, sort_keys=True))
    print("Unknown layers: " + json.dumps(result.get("layer_unknown_counts") or {}, sort_keys=True))
    print("History coverage: " + json.dumps(result.get("history_coverage") or {}, sort_keys=True))
    print("Authority: READ ONLY / THRESHOLDS UNCHANGED / UNKNOWN NOT PROMOTED / LIVE LOCKED")
    return 0 if result.get("status") == "OBSERVED" else 2


def main() -> None:
    raise SystemExit(asyncio.run(run(parser().parse_args())))


if __name__ == "__main__":
    main()
