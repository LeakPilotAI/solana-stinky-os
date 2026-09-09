"""Logging helpers for factual funding-scan coverage diagnostics."""

from __future__ import annotations

from entity_resolver.chain_evidence import FundingScanResult


def funding_scan_log_fields(wallet: str, result: FundingScanResult) -> dict[str, object]:
    """Return stable structured fields for positive, zero, and RPC-failed scans."""
    return {
        "wallet": wallet,
        "rpc_success": result.rpc_success,
        "signatures_requested": result.signatures_requested,
        "signatures_returned": result.signatures_returned,
        "signatures_examined": result.signatures_examined,
        "inbound_native_sol_transfers": len(result.transfers),
        "zero_result": result.rpc_success and not result.transfers,
    }
