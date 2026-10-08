from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.db import get_session


router = APIRouter(
    prefix="/v1/intelligence",
    tags=["intelligence"],
)

AUTHORITY = {
    "paper_only": True,
    "read_only": True,
    "performance_validation": False,
    "predictive_authority": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "trade_signal": False,
    "live_execution": False,
    "order_submitted": False,
    "transaction_signed": False,
    "wallet_mutated": False,
    "trading_authority": False,
}

POLICY_VERSION = "genesis-paper-execution-v2"

REQUIRED_MATURE_MINTS = 100
REQUIRED_RUNTIME_SESSIONS = 5
REQUIRED_PRICED_PATHS = 80
MAX_UNKNOWN_FRACTION = 0.20


def summarize_execution_v2(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    mature_mints: set[str] = set()
    priced_mints: set[str] = set()
    sessions: set[tuple[str, int, str]] = set()

    policy_sha256: str | None = None
    prospective_boundary: str | None = None

    for row in rows:
        plan = row.get("plan")
        result = row.get("result")

        if not isinstance(plan, dict):
            plan = {}

        if not isinstance(result, dict):
            result = None

        if policy_sha256 is None:
            value = row.get("policy_sha256")
            if value:
                policy_sha256 = str(value)

        if prospective_boundary is None:
            value = row.get("prospective_boundary")
            if value is not None:
                prospective_boundary = (
                    value.isoformat()
                    if hasattr(value, "isoformat")
                    else str(value)
                )

        status = (
            str(result.get("status"))
            if result and result.get("status")
            else "PENDING"
        )
        counts[status] += 1

        mint = str(row.get("mint") or "").strip()

        if status != "PENDING" and mint:
            mature_mints.add(mint)

        if status == "PAPER_PRICED" and mint:
            priced_mints.add(mint)

        runtime_session = plan.get("runtime_session")

        if (
            status in {"PAPER_PRICED", "REJECTED", "UNKNOWN"}
            and isinstance(runtime_session, dict)
            and runtime_session.get("identity_verified") is True
            and runtime_session.get("service")
            and runtime_session.get("supervisor_pid") is not None
            and runtime_session.get("started_at")
        ):
            sessions.add(
                (
                    str(runtime_session["service"]),
                    int(runtime_session["supervisor_pid"]),
                    str(runtime_session["started_at"]),
                )
            )

    mature_rows = (
        counts["PAPER_PRICED"]
        + counts["REJECTED"]
        + counts["UNKNOWN"]
    )
    mature_count = len(mature_mints)

    unknown_fraction = (
        counts["UNKNOWN"] / mature_rows
        if mature_rows
        else None
    )

    gates = {
        "distinct_mint_mature_plans": {
            "observed": mature_count,
            "required": REQUIRED_MATURE_MINTS,
            "passed": mature_count >= REQUIRED_MATURE_MINTS,
        },
        "verified_runtime_sessions": {
            "observed": len(sessions),
            "required": REQUIRED_RUNTIME_SESSIONS,
            "passed": len(sessions) >= REQUIRED_RUNTIME_SESSIONS,
        },
        "complete_priced_paths": {
            "observed": len(priced_mints),
            "required": REQUIRED_PRICED_PATHS,
            "passed": len(priced_mints) >= REQUIRED_PRICED_PATHS,
        },
        "unknown_fraction": {
            "observed": unknown_fraction,
            "required_max": MAX_UNKNOWN_FRACTION,
            "passed": (
                unknown_fraction is not None
                and unknown_fraction <= MAX_UNKNOWN_FRACTION
            ),
        },
    }

    evaluation_ready = all(
        bool(gate["passed"])
        for gate in gates.values()
    )

    return {
        "status": "OBSERVED" if rows else "UNKNOWN",
        "policy_version": POLICY_VERSION,
        "policy_sha256": policy_sha256,
        "prospective_boundary": prospective_boundary,
        "counts": {
            "PAPER_PRICED": counts["PAPER_PRICED"],
            "REJECTED": counts["REJECTED"],
            "UNKNOWN": counts["UNKNOWN"],
            "PENDING": counts["PENDING"],
        },
        "distinct_mint_mature_plans": mature_count,
        "verified_runtime_sessions": len(sessions),
        "priced_paths": counts["PAPER_PRICED"],
        "unknown_fraction": unknown_fraction,
        "adequacy_gates": gates,
        "adequacy_status": (
            "DESCRIPTIVE_REVIEW_ELIGIBLE"
            if evaluation_ready
            else "INSUFFICIENT_EVIDENCE"
        ),
        "evaluation_ready": evaluation_ready,
        "interpretation":
            "UNVALIDATED_PROSPECTIVE_PAPER_SNAPSHOT_PROXIES",
        "operator_note": (
            "Prospective V2 paper evidence only. "
            "Adequacy authorizes descriptive review only; "
            "it does not establish predictive performance, "
            "risk, quality, or trading authority."
        ),
        **AUTHORITY,
    }


async def execution_v2_operator_summary(
    session: AsyncSession,
) -> dict[str, Any]:
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT
                        p.id,
                        p.policy_version,
                        p.policy_sha256,
                        p.mint,
                        p.plan,
                        r.result,
                        reg.prospective_boundary
                    FROM intelligence_execution_v2_plans p
                    JOIN intelligence_execution_v2_registry reg
                      ON reg.policy_version = p.policy_version
                    LEFT JOIN intelligence_execution_v2_results r
                      ON r.plan_id = p.id
                    WHERE p.policy_version = :policy_version
                    ORDER BY p.id
                    """
                ),
                {"policy_version": POLICY_VERSION},
            )
        ).mappings().all()
    except Exception:
        return {
            "status": "UNKNOWN",
            "policy_version": POLICY_VERSION,
            "adequacy_status": "INSUFFICIENT_EVIDENCE",
            "evaluation_ready": False,
            "missing": [
                "intelligence_execution_v2_evidence",
            ],
            "interpretation":
                "UNVALIDATED_PROSPECTIVE_PAPER_SNAPSHOT_PROXIES",
            "operator_note": (
                "V2 evidence is unavailable. "
                "No performance or trading authority may be inferred."
            ),
            **AUTHORITY,
        }

    return summarize_execution_v2(
        [dict(row) for row in rows]
    )


@router.get("/execution-v2")
async def execution_v2_operator_endpoint(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await execution_v2_operator_summary(session)
