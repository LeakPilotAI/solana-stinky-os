"""Pump.fun create-instruction log decoding.

Strict parsing to reduce false positives from non-Create pump.fun logs.
"""

from __future__ import annotations

import base64
import struct
from typing import Any

import base58
import structlog

from sentinel.models import DetectedLaunch

logger = structlog.get_logger(__name__)

PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"


def _read_string(data: bytes, offset: int) -> tuple[str, int]:
    if offset + 4 > len(data):
        return "", offset
    (length,) = struct.unpack_from("<I", data, offset)
    offset += 4
    if length > 200 or offset + length > len(data):
        return "", offset
    raw = data[offset : offset + length]
    offset += length
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "", offset
    if any(ord(c) < 9 for c in text):
        return "", offset
    return text, offset


def _read_pubkey(data: bytes, offset: int) -> tuple[str, int]:
    if offset + 32 > len(data):
        return "", offset
    raw = data[offset : offset + 32]
    if raw == b"\x00" * 32:
        return "", offset
    key = base58.b58encode(raw).decode("ascii")
    return key, offset + 32


def _is_valid_pubkey(value: str) -> bool:
    if not value or len(value) < 32 or len(value) > 44:
        return False
    try:
        decoded = base58.b58decode(value)
        return len(decoded) == 32
    except Exception:
        return False


def decode_pump_create_program_data(b64: str) -> dict[str, str | None] | None:
    try:
        raw = base64.b64decode(b64)
    except Exception:
        return None

    if len(raw) < 8 + 12:
        return None

    for start in (8, 0):
        offset = start
        name, offset = _read_string(raw, offset)
        symbol, offset = _read_string(raw, offset)
        uri, offset = _read_string(raw, offset)
        mint, offset = _read_pubkey(raw, offset)
        bonding, offset = _read_pubkey(raw, offset)
        user, offset = _read_pubkey(raw, offset)

        if not (_is_valid_pubkey(mint) and _is_valid_pubkey(user)):
            continue
        if mint == user:
            continue
        if not name and not symbol:
            continue

        return {
            "name": name or None,
            "symbol": symbol or None,
            "uri": uri or None,
            "mint": mint,
            "bonding_curve": bonding if _is_valid_pubkey(bonding) else None,
            "deployer": user,
        }
    return None


def parse_logs_notification(
    result: dict[str, Any],
    *,
    signature: str | None = None,
) -> DetectedLaunch | None:
    """Parse a logsSubscribe notification into a DetectedLaunch (strict)."""
    value = result.get("value") or result
    logs: list[str] = value.get("logs") or []
    sig = signature or value.get("signature")

    joined = "\n".join(logs)
    if "Instruction: Create" not in joined:
        return None
    if "Program data:" not in joined:
        return None

    program_data_b64: str | None = None
    for line in logs:
        if "Program data:" in line:
            program_data_b64 = line.split("Program data:", 1)[1].strip()
            break

    if not program_data_b64:
        return None

    decoded = decode_pump_create_program_data(program_data_b64)
    if not decoded or not decoded.get("mint") or not decoded.get("deployer"):
        return None

    return DetectedLaunch(
        mint=str(decoded["mint"]),
        deployer=str(decoded["deployer"]),
        name=decoded.get("name"),  # type: ignore[arg-type]
        symbol=decoded.get("symbol"),  # type: ignore[arg-type]
        uri=decoded.get("uri"),  # type: ignore[arg-type]
        bonding_curve=decoded.get("bonding_curve"),  # type: ignore[arg-type]
        signature=sig,
        source="pump.fun",
        raw={"logs": logs[:30]},
    )
