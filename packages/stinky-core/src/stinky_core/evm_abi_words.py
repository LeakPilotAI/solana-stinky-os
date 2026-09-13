"""Small strict ABI word helpers used by read-only evidence decoders."""
from __future__ import annotations

from .multichain_identity import canonical_chain_address


def word_at(raw: bytes, index: int) -> bytes:
    start = index * 32
    end = start + 32
    if index < 0 or end > len(raw):
        raise ValueError("ABI word out of bounds")
    return raw[start:end]


def uint_from_word(word: bytes) -> int:
    if len(word) != 32:
        raise ValueError("ABI uint word must be 32 bytes")
    return int.from_bytes(word, "big")


def address_from_word(chain: str, word: bytes) -> str:
    if len(word) != 32 or any(word[:12]):
        raise ValueError("address word is not canonically ABI encoded")
    canonical = canonical_chain_address(chain, "0x" + word[12:].hex())
    if canonical is None:
        raise ValueError("decoded address is invalid for chain")
    return canonical


def address_array_at(
    raw: bytes,
    *,
    offset: int,
    minimum_offset: int,
    chain: str,
    require_exact_end: bool = True,
) -> tuple[str, ...]:
    if offset < minimum_offset or offset % 32:
        raise ValueError("dynamic array offset is not canonical")
    if offset + 32 > len(raw):
        raise ValueError("dynamic array offset exceeds payload")
    length = uint_from_word(raw[offset:offset + 32])
    if length < 1:
        raise ValueError("dynamic address array is empty")
    start = offset + 32
    end = start + length * 32
    if end > len(raw):
        raise ValueError("dynamic address array exceeds payload")
    if require_exact_end and end != len(raw):
        raise ValueError("unexpected trailing bytes after dynamic address array")
    return tuple(address_from_word(chain, raw[i:i + 32]) for i in range(start, end, 32))
