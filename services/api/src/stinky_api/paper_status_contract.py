"""Restore immutable policy/readiness observability over the existing DB pool."""
from __future__ import annotations
import json
import re
from sqlalchemy import text
from stinky_api.config import settings

AUTHORITY = {"policy_provisioned": False, "automatic_activation": False}

def positive_int(value):
    if value is None or not re.fullmatch(r"[0-9]+", str(value).strip()):
        return None
    value = int(str(value).strip())
    return value if 0 < value <= 9007199254740991 else None

def readiness(raw, closed, represented, market):
    names = ("min_closed_outcomes", "min_market_cap_samples", "min_outcome_classes")
    criteria = dict(zip(names, (positive_int(v) for v in raw)))
    configured = all(v is not None for v in criteria.values()) and criteria["min_outcome_classes"] <= 3
    criteria["configured"] = configured
    deficits = None if not configured else {
        "closed_outcomes_needed": max(0, criteria["min_closed_outcomes"]-closed),
        "outcome_classes_needed": max(0, criteria["min_outcome_classes"]-represented),
        "market_cap_samples_needed": None if market is None else max(0, criteria["min_market_cap_samples"]-market),
    }
    return {"status": "CRITERIA_CONFIGURED" if configured else "CRITERIA_NOT_SET",
            "criteria": criteria, "deficits": deficits, "observed_market_cap_samples": market,
            "market_cap_samples_available": market is not None, **AUTHORITY}

def decode(value):
    return json.loads(value) if isinstance(value, str) else value

IDENTITY = """'policy_version',r.policy_version,'policy_sha256',r.policy_sha256,
    'provenance',r.policy_payload->'provenance'"""
PROVENANCE = """CASE WHEN r.policy_payload->'provenance'->>'evidence_backed'='true' THEN 'EVIDENCE_BACKED'
    WHEN r.policy_payload->'provenance'->>'evidence_backed'='false' THEN 'MANUAL' ELSE 'UNKNOWN' END"""
REGISTRY_SQL = f"""SELECT jsonb_build_object('policy_version',r.policy_version,'policy_sha256',r.policy_sha256,
    'provenance',{PROVENANCE},'provenance_mode',COALESCE(r.policy_payload->'provenance'->>'mode','UNKNOWN'),
    'policy_identity',jsonb_build_object({IDENTITY}),
    'state',CASE WHEN a.policy_version IS NOT NULL THEN 'ACTIVE' ELSE 'PROVISIONED' END,
    'created_at',r.created_at,'activated_at',a.activated_at) AS payload
    FROM paper_policy_registry r LEFT JOIN paper_policy_active a
    ON a.singleton=TRUE AND a.policy_version=r.policy_version
    ORDER BY r.created_at DESC,r.policy_version DESC LIMIT 51"""
ACTIVE_SQL = f"""SELECT jsonb_build_object('status','ACTIVE','version',r.policy_version,
    'horizon',r.horizon,'notional_usd',r.paper_notional_usd,'policy_sha256',r.policy_sha256,
    'provenance',{PROVENANCE},'provenance_mode',COALESCE(r.policy_payload->'provenance'->>'mode','UNKNOWN'),
    'policy_identity',jsonb_build_object({IDENTITY}),'activated_at',a.activated_at)
    FROM paper_policy_active a JOIN paper_policy_registry r ON r.policy_version=a.policy_version
    WHERE a.singleton=TRUE LIMIT 1"""

async def paper_status_contract(session, *, closed, candidates, represented, first_at, latest_at):
    # Mandatory registry evidence never becomes an invented empty successful list.
    rows = (await session.execute(text(REGISTRY_SQL))).mappings().all()
    registry = [decode(row["payload"]) for row in rows]
    absent = {"version": None, "horizon": None, "notional_usd": None, "policy_sha256": None,
              "provenance": None, "provenance_mode": None, "policy_identity": None, "activated_at": None}
    try:
        async with session.begin_nested():
            active = (await session.execute(text(ACTIVE_SQL))).scalar_one_or_none()
        policy = decode(active) if active is not None else {"status": "NOT_SET", **absent}
    except Exception:
        policy = {"status": "UNKNOWN", **absent}
    try:
        # A missing optional source must not abort the surrounding read transaction.
        async with session.begin_nested():
            market = (await session.execute(text("SELECT COALESCE(max(sample_count),0) FROM market_pattern_outcome_distributions WHERE status='CALIBRATED_EMPIRICAL'"))).scalar_one()
    except Exception:
        market = None
    criteria = readiness((settings.paper_readiness_min_closed_outcomes,
                          settings.paper_readiness_min_market_cap_samples,
                          settings.paper_readiness_min_outcome_classes), closed, represented, market)
    return {"policy": policy, "policy_registry": registry[:50],
            "policy_registry_scope": "LATEST_50_IMMUTABLE_POLICIES",
            "policy_registry_truncated": len(registry)>50,
            "prospective_evidence": {"status": "ACCUMULATING" if candidates else "AWAITING_CANDIDATES",
                "closed_outcomes": closed, "pending_outcomes": max(0,candidates-closed),
                "represented_outcome_classes": represented, "first_candidate_at": first_at,
                "latest_candidate_at": latest_at, "thresholds_invented": False,
                "policy_threshold_proposal": "NOT_EVALUATED_ON_STATUS_SURFACE" if criteria["criteria"]["configured"] else "REQUIRES_EXPLICIT_SUFFICIENCY_CRITERIA",
                "readiness": criteria}}
