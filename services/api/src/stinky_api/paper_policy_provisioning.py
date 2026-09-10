"""Durable, versioned paper-policy provisioning.

Policies are operator-supplied and immutable. Genesis never invents thresholds.
Activation changes only the paper-policy pointer and never grants live authority.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text

AUTHORITY = {
    "paper_only": True,
    "live_execution": False,
    "trading_authority": False,
    "trade_signal": False,
    "rpc_contacted": False,
    "transaction_signed": False,
    "order_submitted": False,
    "wallet_mutated": False,
}
_ALLOWED_HORIZONS = {"5m", "15m", "30m", "1h", "4h", "24h"}


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n and n not in (float("inf"), float("-inf")) else None


def validate_paper_configuration(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {"status": "UNKNOWN", "missing": ["paper_configuration"], **AUTHORITY}
    policy = config.get("paper_policy")
    assumptions = config.get("execution_assumptions")
    notional = _num(config.get("paper_notional_usd"))
    if not isinstance(policy, dict) or not isinstance(assumptions, dict):
        return {"status": "UNKNOWN", "missing": ["paper_policy", "execution_assumptions"], **AUTHORITY}
    missing: list[str] = []
    version = str(policy.get("policy_version") or "").strip()
    horizon = str(policy.get("horizon") or "").strip()
    if not version:
        missing.append("policy_version")
    if horizon not in _ALLOWED_HORIZONS:
        missing.append("horizon")
    for key in ("min_runner_probability", "max_fade_probability", "min_nonnegative_market_cap_probability"):
        n = _num(policy.get(key))
        if n is None or not 0.0 <= n <= 1.0:
            missing.append(key)
    for key in ("entry_slippage_bps", "exit_slippage_bps", "entry_fee_bps", "exit_fee_bps", "latency_ms"):
        n = _num(assumptions.get(key))
        if n is None or n < 0:
            missing.append(key)
    if notional is None or notional <= 0 or notional > 20.0:
        missing.append("paper_notional_usd")
    if missing:
        return {"status": "UNKNOWN", "missing": missing, **AUTHORITY}
    canonical = {
        "paper_policy": {
            "policy_version": version,
            "horizon": horizon,
            "min_runner_probability": float(policy["min_runner_probability"]),
            "max_fade_probability": float(policy["max_fade_probability"]),
            "min_nonnegative_market_cap_probability": float(policy["min_nonnegative_market_cap_probability"]),
        },
        "execution_assumptions": {
            key: float(assumptions[key])
            for key in ("entry_slippage_bps", "exit_slippage_bps", "entry_fee_bps", "exit_fee_bps", "latency_ms")
        },
        "paper_notional_usd": float(notional),
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return {"status": "VALIDATED", "configuration": canonical, "policy_sha256": hashlib.sha256(raw).hexdigest(), **AUTHORITY}


async def provision_paper_policy(session, config: dict[str, Any], *, activate: bool = True) -> dict[str, Any]:
    checked = validate_paper_configuration(config)
    if checked.get("status") != "VALIDATED":
        return checked
    canonical = checked["configuration"]
    policy = canonical["paper_policy"]
    assumptions = canonical["execution_assumptions"]
    version = policy["policy_version"]
    sha = checked["policy_sha256"]
    existing = (await session.execute(text("SELECT policy_sha256 FROM paper_policy_registry WHERE policy_version=:v"), {"v": version})).first()
    if existing and existing[0] != sha:
        return {"status": "BLOCKED", "reason": "policy_version_already_bound_to_different_payload", "policy_version": version, **AUTHORITY}
    if not existing:
        await session.execute(text("""
            INSERT INTO paper_policy_registry(
              policy_version,horizon,min_runner_probability,max_fade_probability,
              min_nonnegative_market_cap_probability,entry_slippage_bps,exit_slippage_bps,
              entry_fee_bps,exit_fee_bps,latency_ms,paper_notional_usd,policy_sha256,policy_payload
            ) VALUES (
              :v,:h,:r,:f,:u,:es,:xs,:ef,:xf,:lat,:n,:sha,CAST(:payload AS jsonb)
            )
        """), {
            "v": version, "h": policy["horizon"], "r": policy["min_runner_probability"],
            "f": policy["max_fade_probability"], "u": policy["min_nonnegative_market_cap_probability"],
            "es": assumptions["entry_slippage_bps"], "xs": assumptions["exit_slippage_bps"],
            "ef": assumptions["entry_fee_bps"], "xf": assumptions["exit_fee_bps"],
            "lat": assumptions["latency_ms"], "n": canonical["paper_notional_usd"], "sha": sha,
            "payload": json.dumps(canonical, sort_keys=True, separators=(",", ":")),
        })
    if activate:
        await session.execute(text("""
            INSERT INTO paper_policy_active(singleton,policy_version,activated_at)
            VALUES (TRUE,:v,now())
            ON CONFLICT (singleton) DO UPDATE SET policy_version=EXCLUDED.policy_version,activated_at=now()
        """), {"v": version})
        await session.execute(text("INSERT INTO paper_policy_activation_audit(policy_version,policy_sha256) VALUES (:v,:sha)"), {"v": version, "sha": sha})
    await session.commit()
    return {"status": "ACTIVE" if activate else "PROVISIONED", "policy_version": version, "policy_sha256": sha, **AUTHORITY}


async def load_active_paper_configuration(session) -> dict[str, Any]:
    row = (await session.execute(text("""
        SELECT r.policy_payload,r.policy_sha256,r.policy_version,a.activated_at
        FROM paper_policy_active a JOIN paper_policy_registry r ON r.policy_version=a.policy_version
        WHERE a.singleton=TRUE LIMIT 1
    """))).mappings().first()
    if not row:
        return {"configured": False, "missing": ["active_paper_policy"], **AUTHORITY}
    payload = row["policy_payload"] if isinstance(row["policy_payload"], dict) else None
    checked = validate_paper_configuration(payload or {})
    if checked.get("status") != "VALIDATED" or checked.get("policy_sha256") != row["policy_sha256"]:
        return {"configured": False, "missing": ["active_paper_policy_integrity"], **AUTHORITY}
    return {"configured": True, **checked["configuration"], "policy_sha256": row["policy_sha256"], "activated_at": row["activated_at"], **AUTHORITY}
