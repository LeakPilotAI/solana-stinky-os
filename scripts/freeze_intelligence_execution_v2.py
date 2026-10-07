"""Freeze a new prospective PAPER-only hypothesis; never read outcome evidence."""
from __future__ import annotations
import asyncio
import hashlib
import json
import os
from pathlib import Path
import asyncpg

VERSION = "genesis-paper-execution-v2"
ROOT = Path(__file__).resolve().parents[1]

def policy():
    return {
        "version": VERSION, "source_policy": "genesis-evidence-paper-v3",
        "source_threshold": {"comparison": ">", "score": 50},
        "entry_latency_sec": 30, "hold_sec": 60, "observation_tolerance_sec": 30,
        "min_entry_liquidity_usd": 1000, "paper_notional_usd": 100,
        "entry_fee_pct": 0.005, "entry_slippage_pct": 0.005,
        "exit_fee_pct": 0.005, "exit_slippage_pct": 0.005,
        "entry_rule": "first_positive_snapshot_at_or_after_target_within_tolerance",
        "exit_rule": "fixed_entry_target_plus_hold_first_positive_snapshot_within_tolerance",
        "admission_rule": "post_boundary_migration_score_decision_and_plan_before_entry_target",
        "maturity_rule": "exit_target_plus_observation_tolerance",
        "adequacy": {"distinct_mint_mature_plans": 100, "recorded_runtime_sessions": 5,
                     "complete_paths": 80, "max_unknown_fraction": 0.2},
        "evaluation": "descriptive_paper_only_no_profitability_or_significance_claim",
        "historical_selection": "single_60s_hypothesis_no_further_parameter_search",
        "paper_only": True, "live_execution": False, "trading_authority": False,
        "transaction_signing": False, "order_submission": False,
        "wallet_mutation": False, "retuning_permitted": False,
    }

def policy_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

def verify_registry(row):
    payload = json.loads(row["policy"]) if isinstance(row["policy"], str) else row["policy"]
    if payload != policy() or row["policy_sha256"] != policy_hash(payload):
        raise ValueError("frozen_policy_mismatch")
    return {"version": VERSION, "policy_sha256": row["policy_sha256"],
            "prospective_boundary": row["prospective_boundary"].isoformat(),
            "paper_only": True, "live_execution": False}

async def freeze(conn):
    payload = policy()
    async with conn.transaction():
        await conn.execute((ROOT / "services/post-migration-collector/migrations/007_intelligence_execution_v2_registry.sql").read_text(encoding="utf-8"))
        await conn.execute("""INSERT INTO intelligence_execution_v2_registry
            (policy_version,policy_sha256,policy,prospective_boundary)
            VALUES($1,$2,$3::jsonb,clock_timestamp())
            ON CONFLICT(policy_version) DO NOTHING""", VERSION, policy_hash(payload), json.dumps(payload))
        row = await conn.fetchrow("SELECT * FROM intelligence_execution_v2_registry WHERE policy_version=$1", VERSION)
        return verify_registry(row)

async def main():
    url = os.getenv("STINKY_DATABASE_URL", "postgresql://stinky:stinky@127.0.0.1:5433/stinky")
    conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://", 1), timeout=10, command_timeout=30)
    try:
        print(json.dumps(await freeze(conn), sort_keys=True))
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
