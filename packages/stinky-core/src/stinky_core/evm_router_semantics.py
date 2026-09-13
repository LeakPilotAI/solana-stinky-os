"""Conservative semantic decoding for supported historical EVM router-call evidence."""
from __future__ import annotations

from dataclasses import dataclass

from .multichain_identity import canonical_chain_address


@dataclass(frozen=True, slots=True)
class RouterCalldataSemantics:
    selector: str
    signature: str | None
    family: str | None
    amount_in: int | None
    amount_out_min: int | None
    path: tuple[str, ...]
    recipient: str | None
    deadline: int | None
    status: str
    issues: tuple[str, ...]


_SUPPORTED = {
    "38ed1739": (
        "swapExactTokensForTokens(uint256,uint256,address[],address,uint256)",
        "UNISWAP_V2_STYLE_EXACT_INPUT_TOKEN_TO_TOKEN",
        5, 0, 1, 2, 3, 4, False,
    ),
    "18cbafe5": (
        "swapExactTokensForETH(uint256,uint256,address[],address,uint256)",
        "UNISWAP_V2_STYLE_EXACT_INPUT_TOKEN_TO_NATIVE",
        5, 0, 1, 2, 3, 4, False,
    ),
    "7ff36ab5": (
        "swapExactETHForTokens(uint256,address[],address,uint256)",
        "UNISWAP_V2_STYLE_EXACT_INPUT_NATIVE_TO_TOKEN",
        4, None, 0, 1, 2, 3, True,
    ),
}


def _word(raw: bytes, index: int) -> bytes:
    start = index * 32
    end = start + 32
    if end > len(raw):
        raise ValueError("ABI word out of bounds")
    return raw[start:end]


def _uint(word: bytes) -> int:
    return int.from_bytes(word, "big")


def _address(chain: str, word: bytes) -> str:
    if len(word) != 32 or any(word[:12]):
        raise ValueError("address word is not canonically ABI encoded")
    canonical = canonical_chain_address(chain, "0x" + word[12:].hex())
    if canonical is None:
        raise ValueError("decoded address is invalid for chain")
    return canonical


def decode_router_calldata(*, chain: str, calldata: str, value: int = 0) -> RouterCalldataSemantics:
    if value < 0:
        raise ValueError("value must be non-negative")
    if not isinstance(calldata, str) or not calldata.startswith("0x") or len(calldata) < 10 or len(calldata) % 2:
        raise ValueError("calldata must contain a complete 4-byte selector")
    try:
        raw = bytes.fromhex(calldata[2:])
    except ValueError as exc:
        raise ValueError("calldata must be valid hex") from exc

    selector = raw[:4].hex()
    spec = _SUPPORTED.get(selector)
    if spec is None:
        return RouterCalldataSemantics(
            selector, None, None, None, None, (), None, None,
            "UNSUPPORTED_ROUTER_SELECTOR",
            ("SELECTOR_NOT_IN_CONSERVATIVE_ROUTER_REGISTRY",),
        )

    signature, family, head_words, amount_in_i, min_out_i, path_i, recipient_i, deadline_i, native_input = spec
    payload = raw[4:]
    try:
        head_size = head_words * 32
        if len(payload) < head_size:
            raise ValueError("calldata shorter than supported ABI head")
        if not native_input and value != 0:
            raise ValueError("nonpayable supported signature received non-zero value")
        amount_in = value if native_input else _uint(_word(payload, amount_in_i))
        amount_out_min = _uint(_word(payload, min_out_i))
        path_offset = _uint(_word(payload, path_i))
        recipient = _address(chain, _word(payload, recipient_i))
        deadline = _uint(_word(payload, deadline_i))
        if path_offset < head_size or path_offset % 32:
            raise ValueError("path offset is not canonical")
        if path_offset + 32 > len(payload):
            raise ValueError("path offset exceeds calldata")
        path_len = _uint(payload[path_offset:path_offset + 32])
        if path_len < 2:
            raise ValueError("router path must contain at least two addresses")
        path_start = path_offset + 32
        path_end = path_start + (path_len * 32)
        if path_end != len(payload):
            raise ValueError("supported calldata has unexpected trailing or missing bytes")
        path = tuple(_address(chain, payload[i:i + 32]) for i in range(path_start, path_end, 32))
    except (ValueError, IndexError, TypeError) as exc:
        return RouterCalldataSemantics(
            selector, signature, family, None, None, (), None, None,
            "MALFORMED_SUPPORTED_ROUTER_CALLDATA", (str(exc),),
        )

    return RouterCalldataSemantics(
        selector, signature, family, amount_in, amount_out_min, path, recipient, deadline,
        "SUPPORTED_ROUTER_CALLDATA_SEMANTICS", (),
    )
