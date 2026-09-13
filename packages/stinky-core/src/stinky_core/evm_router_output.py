"""Strict decoding for ABI uint256[] return data from supported router calls."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RouterOutputSemantics:
    amounts: tuple[int, ...]
    amount_in: int | None
    amount_out: int | None
    minimum_output_satisfied: bool | None
    status: str
    issues: tuple[str, ...]


def _uint(word: bytes) -> int:
    return int.from_bytes(word, "big")


def decode_uint256_array_output(
    result: str | None,
    *,
    expected_length: int | None = None,
    expected_input: int | None = None,
    minimum_output: int | None = None,
) -> RouterOutputSemantics:
    if result is None:
        return RouterOutputSemantics((), None, None, None, "NO_QUORUM_OUTPUT", ("CALL_RESULT_NOT_AVAILABLE",))
    if not isinstance(result, str) or not result.startswith("0x") or len(result) % 2:
        return RouterOutputSemantics((), None, None, None, "MALFORMED_ROUTER_OUTPUT", ("RESULT_NOT_COMPLETE_HEX",))
    try:
        raw = bytes.fromhex(result[2:])
        if len(raw) < 64 or len(raw) % 32:
            raise ValueError("uint256[] result must contain complete ABI words")
        if _uint(raw[:32]) != 32:
            raise ValueError("uint256[] result must use canonical top-level offset")
        length = _uint(raw[32:64])
        if 64 + (length * 32) != len(raw):
            raise ValueError("uint256[] result length does not match encoded bytes")
        amounts = tuple(_uint(raw[i:i + 32]) for i in range(64, len(raw), 32))
        if expected_length is not None and length != expected_length:
            raise ValueError("router output amount count does not match decoded path length")
        if not amounts:
            raise ValueError("router output amount array is empty")
        if expected_input is not None and amounts[0] != expected_input:
            raise ValueError("router output input amount does not match decoded exact input")
    except ValueError as exc:
        return RouterOutputSemantics((), None, None, None, "MALFORMED_ROUTER_OUTPUT", (str(exc),))

    amount_out = amounts[-1]
    minimum_satisfied = amount_out >= minimum_output if minimum_output is not None else None
    return RouterOutputSemantics(
        amounts,
        amounts[0],
        amount_out,
        minimum_satisfied,
        "DECODED_UINT256_ARRAY_OUTPUT",
        (),
    )
