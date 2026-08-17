"""Pump.fun → PumpSwap migration (graduation) detection.

Listens to migration program:
  39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg

Parses "Instruction: Migrate" + Program data event for mint + pool.
Only brand-new migrations (skips "already migrated").

Hardening (v0.2):
  - Case-insensitive Migrate detection
  - Try every Program data blob (not only first)
  - Prefer the richest (longest) successful decode
  - Parse from full getTransaction logMessages when logsSubscribe truncates
"""

from __future__ import annotations

import base64
import struct
from typing import Any

import base58
import structlog

from sentinel.models import DetectedMigration

logger = structlog.get_logger(__name__)

# Migration wrapper program (emits Migrate events)
MIGRATION_PROGRAM = "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"
# Pump.fun bonding curve program
PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
# PumpSwap AMM destination
PUMPSWAP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WSOL_MINT = "So11111111111111111111111111111111111111112"


def _read_pubkey(data: bytes, offset: int) -> tuple[str, int]:
    if offset + 32 > len(data):
        return "", offset
    key = base58.b58encode(data[offset : offset + 32]).decode("ascii")
    return key, offset + 32


def _read_u64(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 8 > len(data):
        return 0, offset
    (value,) = struct.unpack_from("<Q", data, offset)
    return value, offset + 8


def _read_i64(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 8 > len(data):
        return 0, offset
    (value,) = struct.unpack_from("<q", data, offset)
    return value, offset + 8


def _read_u16(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 2 > len(data):
        return 0, offset
    (value,) = struct.unpack_from("<H", data, offset)
    return value, offset + 2


def _read_u8(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 1 > len(data):
        return 0, offset
    return data[offset], offset + 1


def parse_migrate_program_data(b64: str) -> dict[str, Any] | None:
    """Parse migration event blob from Program data log.

    Layout (after 8-byte discriminator), matching chainstack / pump migration event:
      timestamp i64, index u16, creator pubkey, baseMint, quoteMint,
      baseMintDecimals u8, quoteMintDecimals u8,
      baseAmountIn u64, quoteAmountIn u64, poolBaseAmount u64, poolQuoteAmount u64,
      minimumLiquidity u64, initialLiquidity u64, lpTokenAmountOut u64,
      poolBump u8, pool pubkey, lpMint pubkey,
      userBaseTokenAccount, userQuoteTokenAccount
    """
    try:
        raw = base64.b64decode(b64)
    except Exception:
        return None
    if len(raw) < 8 + 32 * 3:
        return None

    offset = 8  # skip discriminator
    try:
        _ts, offset = _read_i64(raw, offset)
        _index, offset = _read_u16(raw, offset)
        creator, offset = _read_pubkey(raw, offset)
        base_mint, offset = _read_pubkey(raw, offset)
        quote_mint, offset = _read_pubkey(raw, offset)
        _bd, offset = _read_u8(raw, offset)
        _qd, offset = _read_u8(raw, offset)
        base_amount_in, offset = _read_u64(raw, offset)
        quote_amount_in, offset = _read_u64(raw, offset)
        _pba, offset = _read_u64(raw, offset)
        _pqa, offset = _read_u64(raw, offset)
        _min_liq, offset = _read_u64(raw, offset)
        _init_liq, offset = _read_u64(raw, offset)
        _lp_out, offset = _read_u64(raw, offset)
        _bump, offset = _read_u8(raw, offset)
        pool, offset = _read_pubkey(raw, offset)
        lp_mint, offset = _read_pubkey(raw, offset)
    except Exception as exc:
        logger.debug("migration.parse_failed", error=str(exc))
        return None

    if not base_mint or not pool:
        return None
    # Prefer non-WSOL as the token mint
    mint = base_mint
    if base_mint == WSOL_MINT and quote_mint and quote_mint != WSOL_MINT:
        mint = quote_mint

    return {
        "mint": mint,
        "pool": pool,
        "creator": creator or None,
        "quote_mint": quote_mint or None,
        "base_amount_in": base_amount_in,
        "quote_amount_in": quote_amount_in,
        "lp_mint": lp_mint or None,
        "blob_len": len(raw),
    }


def _is_migrate_instruction(logs: list[str]) -> bool:
    joined = "\n".join(logs).lower()
    return "instruction: migrate" in joined


def _is_already_migrated(logs: list[str]) -> bool:
    joined = "\n".join(logs).lower()
    return "already migrated" in joined


def _is_anchor_error(logs: list[str]) -> bool:
    joined = "\n".join(logs)
    return "AnchorError thrown" in joined or "Error processing Instruction" in joined


def _extract_program_data_blobs(logs: list[str]) -> list[str]:
    blobs: list[str] = []
    for line in logs:
        if "Program data:" in line:
            blob = line.split("Program data:", 1)[1].strip()
            if blob:
                blobs.append(blob)
    # Longest first — richer event payloads decode more reliably
    blobs.sort(key=len, reverse=True)
    return blobs


def _migration_from_parsed(
    parsed: dict[str, Any],
    *,
    signature: str | None,
    logs: list[str],
    source: str,
) -> DetectedMigration:
    return DetectedMigration(
        mint=str(parsed["mint"]),
        pool=str(parsed["pool"]),
        creator=parsed.get("creator"),
        quote_mint=parsed.get("quote_mint"),
        base_amount_in=parsed.get("base_amount_in"),
        quote_amount_in=parsed.get("quote_amount_in"),
        lp_mint=parsed.get("lp_mint"),
        signature=signature,
        destination="pumpswap",
        source=source,
        raw={"logs": logs[:40], "blob_len": parsed.get("blob_len")},
    )


def parse_migration_logs(
    result: dict[str, Any],
    *,
    signature: str | None = None,
    source: str = "pump.fun-migrate",
) -> DetectedMigration | None:
    """Parse logsSubscribe notification for a successful new migration."""
    value = result.get("value") or result
    logs: list[str] = value.get("logs") or []
    sig = signature or value.get("signature")

    if not logs:
        return None

    if not _is_migrate_instruction(logs):
        return None
    if _is_already_migrated(logs):
        return None
    if _is_anchor_error(logs):
        return None

    blobs = _extract_program_data_blobs(logs)
    if not blobs:
        logger.info(
            "migration.migrate_seen_no_program_data",
            signature=sig,
            log_lines=len(logs),
        )
        return None

    for blob in blobs:
        parsed = parse_migrate_program_data(blob)
        if parsed:
            return _migration_from_parsed(
                parsed, signature=sig, logs=logs, source=source
            )

    logger.info(
        "migration.migrate_seen_parse_failed",
        signature=sig,
        blobs_tried=len(blobs),
        max_blob_len=max(len(b) for b in blobs),
    )
    return None


def parse_migration_from_transaction(
    tx: dict[str, Any],
    *,
    signature: str | None = None,
) -> DetectedMigration | None:
    """Parse a full getTransaction result (json / jsonParsed) for migration.

    Used when logsSubscribe truncates Program data (known gap per Chainstack).
    """
    if not tx:
        return None
    meta = tx.get("meta") or {}
    if meta.get("err"):
        return None
    logs: list[str] = meta.get("logMessages") or meta.get("logs") or []
    sig = signature
    if not sig:
        txn = tx.get("transaction") or {}
        if isinstance(txn, dict):
            sigs = txn.get("signatures") or []
            if sigs:
                sig = sigs[0]
    return parse_migration_logs(
        {"value": {"logs": logs, "signature": sig}},
        signature=sig,
        source="pump.fun-migrate-rpc",
    )


def looks_like_migrate_attempt(result: dict[str, Any]) -> bool:
    """True if logs mention Migrate (even if we couldn't fully parse)."""
    value = result.get("value") or result
    logs: list[str] = value.get("logs") or []
    if not logs:
        return False
    if not _is_migrate_instruction(logs):
        return False
    if _is_already_migrated(logs):
        return False
    return True
