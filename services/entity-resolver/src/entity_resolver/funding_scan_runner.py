"""Run and log one bounded buyer funding scan."""

from __future__ import annotations

import httpx
import structlog

from entity_resolver.chain_evidence import FundingScanResult, scan_recent_inbound_transfers
from entity_resolver.funding_diagnostics import funding_scan_log_fields

logger = structlog.get_logger(__name__)


async def run_funding_scan(
    client: httpx.AsyncClient,
    *,
    rpc_url: str,
    wallet: str,
    signature_limit: int,
) -> FundingScanResult:
    result = await scan_recent_inbound_transfers(
        client,
        rpc_url=rpc_url,
        wallet=wallet,
        signature_limit=signature_limit,
    )
    fields = funding_scan_log_fields(wallet, result)
    if result.rpc_success:
        logger.info("entity.wallet_funding_scan_completed", **fields)
    else:
        logger.warning("entity.wallet_funding_scan_rpc_unavailable", **fields)
    return result
