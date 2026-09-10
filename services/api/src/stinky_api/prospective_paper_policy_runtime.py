"""Registry-authoritative prospective paper producer runtime.

The durable active policy is the only source of paper thresholds. Environment paper
variables are cleared when no active registry policy exists, so stale local env
values cannot silently create paper decisions.
"""
from __future__ import annotations

import asyncio
import json
import os

from stinky_api.db import SessionLocal
from stinky_api.paper_policy_provisioning import load_active_paper_configuration
from stinky_api import prospective_paper_intake_producer as producer

_KEYS = {
    "STINKY_PAPER_POLICY_VERSION": ("paper_policy", "policy_version"),
    "STINKY_PAPER_HORIZON": ("paper_policy", "horizon"),
    "STINKY_PAPER_MIN_RUNNER_PROBABILITY": ("paper_policy", "min_runner_probability"),
    "STINKY_PAPER_MAX_FADE_PROBABILITY": ("paper_policy", "max_fade_probability"),
    "STINKY_PAPER_MIN_NONNEGATIVE_MARKET_CAP_PROBABILITY": ("paper_policy", "min_nonnegative_market_cap_probability"),
    "STINKY_PAPER_ENTRY_SLIPPAGE_BPS": ("execution_assumptions", "entry_slippage_bps"),
    "STINKY_PAPER_EXIT_SLIPPAGE_BPS": ("execution_assumptions", "exit_slippage_bps"),
    "STINKY_PAPER_ENTRY_FEE_BPS": ("execution_assumptions", "entry_fee_bps"),
    "STINKY_PAPER_EXIT_FEE_BPS": ("execution_assumptions", "exit_fee_bps"),
    "STINKY_PAPER_LATENCY_MS": ("execution_assumptions", "latency_ms"),
    "STINKY_PAPER_NOTIONAL_USD": (None, "paper_notional_usd"),
}


def _clear_policy_env() -> None:
    for key in _KEYS:
        os.environ.pop(key, None)


def _apply(config: dict) -> None:
    _clear_policy_env()
    if config.get("configured") is not True:
        return
    for env_key, (section, key) in _KEYS.items():
        value = config.get(key) if section is None else (config.get(section) or {}).get(key)
        if value is not None:
            os.environ[env_key] = str(value)


async def sync_active_policy() -> dict:
    async with SessionLocal() as session:
        config = await load_active_paper_configuration(session)
    _apply(config)
    return config


async def run_forever() -> None:
    last_version = object()
    while True:
        try:
            config = await sync_active_policy()
            version = (config.get("paper_policy") or {}).get("policy_version") if config.get("configured") else None
            if version != last_version:
                print(json.dumps({
                    "status": "PAPER_POLICY_ACTIVE" if version else "PAPER_POLICY_NOT_SET",
                    "policy_version": version,
                    "paper_only": True,
                    "live_execution": False,
                    "trading_authority": False,
                }, sort_keys=True), flush=True)
                last_version = version
            result = await producer.tick()
            if result["new_candidates"] or result["canonical_outcomes_attached"] or result["close_intakes_enqueued"]:
                print(json.dumps(result, sort_keys=True), flush=True)
        except Exception as exc:
            _clear_policy_env()
            print(json.dumps({"status": "UNKNOWN", "error": type(exc).__name__, "paper_only": True, "live_execution": False, "trading_authority": False}), flush=True)
        await asyncio.sleep(2.0)


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
