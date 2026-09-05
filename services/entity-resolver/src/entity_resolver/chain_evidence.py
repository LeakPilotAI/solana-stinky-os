"""Read direct native-SOL transfer evidence from Solana JSON-RPC."""

from __future__ import annotations

from typing import Any

import httpx


SYSTEM_PROGRAM = "11111111111111111111111111111111"


async def fetch_native_transfers(
    client: httpx.AsyncClient,
    *,
    rpc_url: str,
    signature: str,
) -> list[dict[str, Any]]:
    """Return directly parsed System Program SOL transfers for one transaction.

    This intentionally recognizes only the canonical parsed System Program
    ``transfer`` instruction. It does not infer ownership, intent, identity,
    quality, risk, or coordination.
    """
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            signature,
            {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0,
                "commitment": "confirmed",
            },
        ],
    }
    try:
        response = await client.post(rpc_url, json=body)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return []

    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        return []

    transaction = result.get("transaction") or {}
    message = transaction.get("message") or {}
    instructions = list(message.get("instructions") or [])
    meta = result.get("meta") or {}
    for group in meta.get("innerInstructions") or []:
        instructions.extend(group.get("instructions") or [])

    observed_at = result.get("blockTime")
    slot = result.get("slot")
    transfers: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()

    for instruction in instructions:
        if not isinstance(instruction, dict):
            continue
        if instruction.get("program") != "system":
            continue
        parsed = instruction.get("parsed")
        if not isinstance(parsed, dict) or parsed.get("type") != "transfer":
            continue
        info = parsed.get("info")
        if not isinstance(info, dict):
            continue
        source = info.get("source")
        destination = info.get("destination")
        lamports = info.get("lamports")
        if not isinstance(source, str) or not source:
            continue
        if not isinstance(destination, str) or not destination or source == destination:
            continue
        try:
            amount = int(lamports)
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        if source == SYSTEM_PROGRAM or destination == SYSTEM_PROGRAM:
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
