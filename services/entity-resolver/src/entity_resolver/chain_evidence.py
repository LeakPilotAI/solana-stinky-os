"""Read direct native-SOL transfer evidence from Solana JSON-RPC."""

from __future__ import annotations

from typing import Any

import httpx


SYSTEM_PROGRAM = "11111111111111111111111111111111"


async def _rpc(
    client: httpx.AsyncClient,
    *,
    rpc_url: str,
    method: str,
    params: list[Any],
) -> Any:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        response = await client.post(rpc_url, json=body)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("error"):
        return None
    return payload.get("result")


async def fetch_native_transfers(
    client: httpx.AsyncClient,
    *,
    rpc_url: str,
    signature: str,
) -> list[dict[str, Any]]:
    """Return direct System Program SOL transfers for one transaction."""
    result = await _rpc(
        client,
        rpc_url=rpc_url,
        method="getTransaction",
        params=[
            signature,
            {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0,
                "commitment": "confirmed",
            },
        ],
    )
    return _parse_native_transfers(result, signature=signature)


async def fetch_recent_inbound_transfers(
    client: httpx.AsyncClient,
    *,
    rpc_url: str,
    wallet: str,
    signature_limit: int = 20,
) -> list[dict[str, Any]]:
    """Scan recent wallet transactions and keep only inbound native-SOL transfers.

    The destination must equal the observed wallet. This avoids classifying the
    wallet's ordinary SOL payments to pools/programs as funding evidence.
    """
    limit = max(1, min(int(signature_limit), 50))
    signatures = await _rpc(
        client,
        rpc_url=rpc_url,
        method="getSignaturesForAddress",
        params=[wallet, {"limit": limit, "commitment": "confirmed"}],
    )
    if not isinstance(signatures, list):
        return []

    transfers: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, str]] = set()
    for row in signatures:
        if not isinstance(row, dict) or row.get("err"):
            continue
        signature = row.get("signature")
        if not isinstance(signature, str) or not signature:
            continue
        for transfer in await fetch_native_transfers(
            client, rpc_url=rpc_url, signature=signature
        ):
            if transfer.get("destination_wallet") != wallet:
                continue
            key = (
                str(transfer["source_wallet"]),
                str(transfer["destination_wallet"]),
                int(transfer["amount_lamports"]),
                str(transfer["signature"]),
            )
            if key in seen:
                continue
            seen.add(key)
            transfers.append(transfer)
    return transfers


def _parse_native_transfers(
    result: Any,
    *,
    signature: str,
) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    transaction = result.get("transaction") or {}
    message = transaction.get("message") or {}
    instructions = list(message.get("instructions") or [])
    meta = result.get("meta") or {}
    for group in meta.get("innerInstructions") or []:
        if isinstance(group, dict):
            instructions.extend(group.get("instructions") or [])

    observed_at = result.get("blockTime")
    slot = result.get("slot")
    transfers: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()

    for instruction in instructions:
        if not isinstance(instruction, dict) or instruction.get("program") != "system":
            continue
        parsed = instruction.get("parsed")
        if not isinstance(parsed, dict) or parsed.get("type") != "transfer":
            continue
        info = parsed.get("info")
        if not isinstance(info, dict):
            continue
        source = info.get("source")
        destination = info.get("destination")
        if not isinstance(source, str) or not source:
            continue
        if not isinstance(destination, str) or not destination or source == destination:
            continue
        try:
            amount = int(info.get("lamports"))
        except (TypeError, ValueError):
            continue
        if amount <= 0 or source == SYSTEM_PROGRAM or destination == SYSTEM_PROGRAM:
            continue
        key = (source, destination, amount)
        if key in seen:
            continue
        seen.add(key)
        transfers.append(
            {
                "source_wallet": source,
                "destination_wallet": destination,
                "amount_lamports": amount,
                "signature": signature,
                "slot": slot,
                "observed_at": observed_at,
                "evidence_basis": "direct_system_program_transfer",
            }
        )
    return transfers
