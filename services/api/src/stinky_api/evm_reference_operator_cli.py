"""Explicit CLI surface for durable, read-only reference DEX observation."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from dataclasses import asdict
from pathlib import Path
from urllib import request as urllib_request

from stinky_api.db import SessionLocal
from stinky_api.evm_reference_operator_errors import (
    OperatorArgumentError, OperatorArgumentParser, serialize_operator_failure,
)
from stinky_api.evm_provider_attestation_audit import (
    ProviderAttestationReceipt,
    ProviderAttestationAudit,
    append_provider_attestation_audit,
    validate_provider_attestations,
)
from stinky_api.evm_reference_observation_operator import invoke_reference_dex_observation
from stinky_api.evm_reference_operator_transport import (
    ReferenceDexOperatorPayload,
    build_operator_request,
    serialize_operator_result,
    validate_operator_payload,
)
from stinky_core.evm_consensus import provider_fingerprint
from stinky_core.evm_rpc import EvmReadOnlyRpc, EvmRpcError, decode_rpc_response

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _https_transport(url: str):
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ValueError("reference RPC URL must use HTTPS")

    def transport(_ignored_url: str, payload: bytes, timeout: float) -> dict:
        req = urllib_request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "genesis-reference-operator/1"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - explicit operator config
                body = response.read()
        except Exception as exc:
            raise EvmRpcError(f"RPC request failed: {type(exc).__name__}") from exc
        return decode_rpc_response(body)

    return transport


def build_cli_observers(chain: str, rpc_env_vars: tuple[str, ...]) -> tuple[EvmReadOnlyRpc, ...]:
    if not rpc_env_vars:
        raise ValueError("at least two --rpc-env values are required")
    urls: list[str] = []
    observers: list[EvmReadOnlyRpc] = []
    for env_name in rpc_env_vars:
        if not _ENV_NAME.fullmatch(env_name):
            raise ValueError("RPC environment variable names must be uppercase identifiers")
        url = os.getenv(env_name, "").strip()
        if not url.startswith("https://"):
            raise ValueError(f"{env_name} must contain an HTTPS RPC URL")
        if url in urls:
            raise ValueError("reference RPC providers must use distinct URLs")
        observer = EvmReadOnlyRpc(chain, transport=_https_transport(url))
        observer.rpc_url = url
        urls.append(url)
        observers.append(observer)
    if len(observers) < 2:
        raise ValueError("at least two distinct reference RPC providers are required")
    return tuple(observers)


def attest_cli_observers(observers: tuple[EvmReadOnlyRpc, ...]) -> tuple[ProviderAttestationReceipt, ...]:
    receipts: list[ProviderAttestationReceipt] = []
    for observer in observers:
        observed_chain_id = observer.attest_chain()
        receipts.append(
            ProviderAttestationReceipt(
                provider=provider_fingerprint(observer.rpc_url),
                chain=observer.chain.key,
                chain_id=observed_chain_id,
            )
        )
    if len(receipts) != len(observers):
        raise EvmRpcError("provider attestation receipt is incomplete")
    return tuple(sorted(receipts, key=lambda receipt: receipt.provider))


async def execute_operator_payload(
    payload: ReferenceDexOperatorPayload,
    *,
    rpc_env_vars: tuple[str, ...],
) -> dict:
    validate_operator_payload(payload)
    observers = build_cli_observers(payload.chain, rpc_env_vars)
    provider_attestations = attest_cli_observers(observers)
    validate_provider_attestations(
        provider_attestations, chain=payload.chain, provider_count=len(observers),
    )
    if tuple(row.provider for row in provider_attestations) != tuple(sorted(
        provider_fingerprint(observer.rpc_url) for observer in observers
    )):
        raise EvmRpcError("provider attestation set does not match configured observers")
    schedule, trigger_request = build_operator_request(payload, observers)
    async with SessionLocal() as session:
        try:
            from datetime import datetime, timezone

            result = await invoke_reference_dex_observation(
                session,
                schedule=schedule,
                request=trigger_request,
                now=datetime.now(timezone.utc),
            )
            if result.trigger.triggered:
                state = result.state
                if state is None or result.trigger.run is None or (
                    state.chain, state.pool_address, state.last_completed_block,
                ) != (payload.chain, trigger_request.pool.pool_address, payload.block_number):
                    raise ValueError("completed observation identity required for provider audit")
                await append_provider_attestation_audit(session, ProviderAttestationAudit(
                    chain=state.chain, pool_address=state.pool_address,
                    block_number=state.last_completed_block, completed_at=state.last_completed_at,
                    provider_count=len(observers), provider_attestations=provider_attestations,
                ))
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
    return {
        **serialize_operator_result(result),
        "provider_attestations": [asdict(receipt) for receipt in provider_attestations],
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = OperatorArgumentParser(
        prog="genesis-evm-reference-observe",
        description="Explicit read-only reference DEX observation. No transaction execution.",
    )
    parser.add_argument("--input", required=True, help="Path to the operator JSON payload")
    parser.add_argument(
        "--rpc-env",
        action="append",
        required=True,
        dest="rpc_env_vars",
        help="Environment variable containing one trusted HTTPS RPC URL; repeat for quorum providers",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
        payload = ReferenceDexOperatorPayload.model_validate(raw)
        output = asyncio.run(execute_operator_payload(payload, rpc_env_vars=tuple(args.rpc_env_vars)))
    except Exception as exc:
        print(json.dumps(serialize_operator_failure(exc), sort_keys=True))
        return 2 if isinstance(exc, OperatorArgumentError) else 1
    print(json.dumps({"ok": True, **output}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
