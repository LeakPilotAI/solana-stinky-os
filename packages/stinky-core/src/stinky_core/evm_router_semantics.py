"""Conservative semantic decoding for supported historical EVM router-call evidence."""
from __future__ import annotations

from dataclasses import dataclass

from .evm_abi_words import address_array_at, address_from_word, uint_from_word, word_at


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
        amount_in = value if native_input else uint_from_word(word_at(payload, amount_in_i))
        amount_out_min = uint_from_word(word_at(payload, min_out_i))
        path_offset = uint_from_word(word_at(payload, path_i))
        recipient = address_from_word(chain, word_at(payload, recipient_i))
        deadline = uint_from_word(word_at(payload, deadline_i))
        path = address_array_at(
            payload,
            offset=path_offset,
            minimum_offset=head_size,
            chain=chain,
            require_exact_end=True,
        )
        if len(path) < 2:
            raise ValueError("router path must contain at least two addresses")
    except (ValueError, IndexError, TypeError) as exc:
        return RouterCalldataSemantics(
            selector, signature, family, None, None, (), None, None,
            "MALFORMED_SUPPORTED_ROUTER_CALLDATA", (str(exc),),
        )

    return RouterCalldataSemantics(
        selector, signature, family, amount_in, amount_out_min, path, recipient, deadline,
        "SUPPORTED_ROUTER_CALLDATA_SEMANTICS", (),
    )
