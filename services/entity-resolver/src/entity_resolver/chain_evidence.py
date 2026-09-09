"""Read direct native-SOL transfer evidence from Solana JSON-RPC."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog


SYSTEM_PROGRAM = "11111111111111111111111111111111"
RPC_MIN_METHOD_INTERVAL_SEC = 0.30
RPC_DEFAULT_RATE_LIMIT_COOLDOWN_SEC = 2.5
logger = structlog.get_logger(__name__)
_rpc_gate = asyncio.Lock()
_rpc_last_request_at: dict[str, float] = {}
_rpc_cooldown_until: dict[str, float] = {}


def _clock() -> float:
    return time.monotonic()


async def _pace_rpc_method(method: str) -> None:
    """Serialize public-RPC calls and respect method-level pacing/cooldowns."""
    now = _clock()
    wait_for = max(
        0.0,
        _rpc_cooldown_until.get(method, 0.0) - now,
        (_rpc_last_request_at.get(method, 0.0) + RPC_MIN_METHOD_INTERVAL_SEC) - now,
    )
    if wait_for > 0:
        await asyncio.sleep(wait_for)


@dataclass(frozen=True)
class FundingScanResult:
    """Bounded factual coverage diagnostics for one inbound-funding scan."""

    transfers: list[dict[str, Any]]
    signatures_requested: int
    signatures_returned: int
    signatures_examined: int
    rpc_success: bool


class FundingTransfers(list[dict[str, Any]]):
    """List-compatible transfer result carrying scan availability metadata."""

    def __init__(self, values: list[dict[str, Any]], *, rpc_success: bool) -> None:
        super().__init__(values)
        self.rpc_success = rpc_success


async def _rpc(
    client: httpx.AsyncClient,
    *,
    rpc_url: str,
    method: str,
    params: list[Any],
) -> Any:
    """Perform one bounded JSON-RPC request with public-endpoint pacing."""
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        failure_kind = "unknown"
        status_code: int | None = None
        rpc_error_code: int | None = None
        error_message = ""
        retryable = False
        retry_delay = 0.0

        async with _rpc_gate:
            await _pace_rpc_method(method)
            try:
                response = await client.post(rpc_url, json=body)
                _rpc_last_request_at[method] = _clock()
                status_code = int(response.status_code)
                if response.status_code >= 400:
                    failure_kind = (
                        "http_rate_limited"
                        if response.status_code == 429
                        else "http_server_error"
                        if 500 <= response.status_code < 600
                        else "http_client_error"
                    )
                    retryable = response.status_code == 429 or 500 <= response.status_code < 600
                    error_message = response.text[:160]
                    if response.status_code == 429:
                        retry_after = response.headers.get("Retry-After")
                        try:
                            retry_delay = max(float(retry_after), 0.0) if retry_after else 0.0
                        except (TypeError, ValueError):
                            retry_delay = 0.0
                        retry_delay = max(retry_delay, RPC_DEFAULT_RATE_LIMIT_COOLDOWN_SEC)
                        _rpc_cooldown_until[method] = max(
                            _rpc_cooldown_until.get(method, 0.0),
                            _clock() + retry_delay,
                        )
                else:
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        failure_kind = "invalid_json"
                        error_message = str(exc)[:160]
                        retryable = True
                    else:
                        if isinstance(payload, dict) and not payload.get("error"):
                            return payload.get("result")
                        failure_kind = "json_rpc_error"
                        error = payload.get("error") if isinstance(payload, dict) else None
                        if isinstance(error, dict):
                            code = error.get("code")
                            if isinstance(code, int):
                                rpc_error_code = code
                            error_message = str(error.get("message") or "")[:160]
                        else:
                            error_message = str(error)[:160]
                        lowered = error_message.lower()
                        retryable = (
                            rpc_error_code in {-32005, -32004, -32603}
                            or "rate" in lowered
                            or "too many" in lowered
                            or "temporar" in lowered
                            or "unavailable" in lowered
                        )
                        if retryable and ("rate" in lowered or "too many" in lowered):
                            retry_delay = RPC_DEFAULT_RATE_LIMIT_COOLDOWN_SEC
                            _rpc_cooldown_until[method] = max(
                                _rpc_cooldown_until.get(method, 0.0),
                                _clock() + retry_delay,
                            )
            except httpx.TimeoutException as exc:
                _rpc_last_request_at[method] = _clock()
                failure_kind = "timeout"
                error_message = str(exc)[:160]
                retryable = True
            except httpx.TransportError as exc:
                _rpc_last_request_at[method] = _clock()
                failure_kind = "transport_error"
                error_message = str(exc)[:160]
                retryable = True

        if retryable and attempt < max_attempts:
            delay = retry_delay or (0.5 * (2 ** (attempt - 1)))
            logger.info(
                "entity.rpc_request_retrying",
                method=method,
                failure_kind=failure_kind,
                status_code=status_code,
                rpc_error_code=rpc_error_code,
                attempt=attempt,
                max_attempts=max_attempts,
                retry_delay_sec=delay,
            )
            await asyncio.sleep(delay)
            continue

        logger.warning(
            "entity.rpc_request_failed",
            method=method,
            failure_kind=failure_kind,
            status_code=status_code,
            rpc_error_code=rpc_error_code,
            error=error_message,
            attempt=attempt,
            max_attempts=max_attempts,
            retryable=retryable,
        )
        return None
    return None


async def fetch_native_transfers(
    client: httpx.AsyncClient,
    *,
    rpc_url: str,
    signature: str,
) -> list[dict[str, Any]]:
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


async def scan_recent_inbound_transfers(
    client: httpx.AsyncClient,
    *,
    rpc_url: str,
    wallet: str,
    signature_limit: int = 50,
) -> FundingScanResult:
    limit = max(1, min(int(signature_limit), 50))
    signatures = await _rpc(
        client,
        rpc_url=rpc_url,
        method="getSignaturesForAddress",
        params=[wallet, {"limit": limit, "commitment": "confirmed"}],
    )
    if not isinstance(signatures, list):
        result = FundingScanResult([], limit, 0, 0, False)
        logger.warning(
            "entity.wallet_funding_scan_rpc_unavailable",
            wallet=wallet,
            rpc_success=False,
            signatures_requested=limit,
            signatures_returned=0,
            signatures_examined=0,
            inbound_native_sol_transfers=0,
            zero_result=False,
        )
        return result

    transfers: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, str]] = set()
    examined = 0
    for row in signatures:
        if not isinstance(row, dict) or row.get("err"):
            continue
        signature = row.get("signature")
        if not isinstance(signature, str) or not signature:
            continue
        examined += 1
        for transfer in await fetch_native_transfers(client, rpc_url=rpc_url, signature=signature):
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
    result = FundingScanResult(transfers, limit, len(signatures), examined, True)
    logger.info(
        "entity.wallet_funding_scan_completed",
        wallet=wallet,
        rpc_success=True,
        signatures_requested=limit,
        signatures_returned=len(signatures),
        signatures_examined=examined,
        inbound_native_sol_transfers=len(transfers),
        zero_result=not transfers,
    )
    return result


async def fetch_recent_inbound_transfers(
    client: httpx.AsyncClient,
    *,
    rpc_url: str,
    wallet: str,
    signature_limit: int = 50,
) -> FundingTransfers:
    """Return transfer evidence while preserving list compatibility for callers/tests."""
    result = await scan_recent_inbound_transfers(
        client,
        rpc_url=rpc_url,
        wallet=wallet,
        signature_limit=signature_limit,
    )
    return FundingTransfers(result.transfers, rpc_success=result.rpc_success)


def _parse_native_transfers(result: Any, *, signature: str) -> list[dict[str, Any]]:
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
