"""Persistent evidence-only shadow/paper worker.

Consumes only caller-persisted frozen evidence bundles. It never fetches market data,
contacts Solana RPC, signs, submits, mutates wallets, or grants trading authority.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from stinky_api.db import SessionLocal
from stinky_api.paper_execution_realism import simulate_paper_execution
from stinky_api.shadow_paper_decision import build_shadow_paper_decision
from stinky_api.shadow_paper_runtime_adapter import adapt_shadow_decision_for_paper

AUTHORITY = {
    "paper_only": True,
    "live_execution": False,
    "trading_authority": False,
    "trade_signal": False,
    "recommendation_authority": False,
    "rpc_contacted": False,
    "transaction_signed": False,
    "order_submitted": False,
    "wallet_mutated": False,
}


def canonical_sha256(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def process_frozen_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"status": "UNKNOWN", "missing": ["frozen_bundle"], **AUTHORITY}
    probability = payload.get("probability_distribution")
    context = payload.get("decision_context")
    policy = payload.get("paper_policy")
    assumptions = payload.get("execution_assumptions")
    if not all(isinstance(x, dict) for x in (probability, context, policy, assumptions)):
        return {"status": "UNKNOWN", "missing": ["complete_frozen_bundle"], **AUTHORITY}

    shadow = build_shadow_paper_decision(probability, context, policy)
    adapted = adapt_shadow_decision_for_paper(shadow)
    paper: dict[str, Any]
    if adapted.get("status") != "OBSERVED" or adapted.get("shadow_action") != "WOULD_ENTER":
        paper = {"status": "NOT_SIMULATED", "reason": "shadow_not_would_enter", **AUTHORITY}
    else:
        paper = simulate_paper_execution(
            adapted,
            assumptions,
            reference_entry_price=payload.get("reference_entry_price"),
            reference_exit_price=payload.get("reference_exit_price"),
            notional_usd=payload.get("paper_notional_usd"),
        )
    return {
        "status": "OBSERVED" if shadow.get("status") == "SHADOW_DECISION" else "UNKNOWN",
        "shadow": shadow,
        "paper": paper,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        **AUTHORITY,
    }


async def process_one() -> bool:
    async with SessionLocal() as session:
        row = (await session.execute(text("""
            SELECT intake_id, mint, payload, payload_sha256
            FROM paper_runtime_intake
            WHERE processed_at IS NULL
            ORDER BY created_at, intake_id
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        """))).mappings().first()
        if row is None:
            return False
        payload = row["payload"]
        if not isinstance(payload, dict) or canonical_sha256(payload) != row["payload_sha256"]:
            result = {"status": "UNKNOWN", "missing": ["payload_hash_match"], **AUTHORITY}
        else:
            result = process_frozen_bundle(payload)
        shadow = result.get("shadow") if isinstance(result.get("shadow"), dict) else {}
        paper = result.get("paper") if isinstance(result.get("paper"), dict) else {}
        await session.execute(text("""
            INSERT INTO paper_runtime_record(
              intake_id, mint, decided_at, shadow_status, shadow_action, paper_status, record
            ) VALUES (
              :intake_id, :mint, CAST(:decided_at AS timestamptz), :shadow_status,
              :shadow_action, :paper_status, CAST(:record AS jsonb)
            )
            ON CONFLICT (intake_id) DO NOTHING
        """), {
            "intake_id": row["intake_id"], "mint": row["mint"],
            "decided_at": shadow.get("decided_at"),
            "shadow_status": str(shadow.get("status") or result.get("status") or "UNKNOWN"),
            "shadow_action": shadow.get("action"),
            "paper_status": str(paper.get("status") or "NOT_SIMULATED"),
            "record": json.dumps(result, sort_keys=True, default=str),
        })
        await session.execute(text("UPDATE paper_runtime_intake SET processed_at=now() WHERE intake_id=:id"), {"id": row["intake_id"]})
        await session.commit()
        return True


async def run_forever(poll_seconds: float = 2.0) -> None:
    while True:
        try:
            worked = await process_one()
        except Exception as exc:
            print("paper-runtime error: %s" % str(exc)[:300], flush=True)
            worked = False
        if not worked:
            await asyncio.sleep(max(0.25, poll_seconds))


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
