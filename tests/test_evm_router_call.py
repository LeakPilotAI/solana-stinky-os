from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

import stinky_core.evm_router_semantics as semantics
from stinky_core.evm_router_swap import _normalize_calldata


def test_router_calldata_validation_preserves_canonical_hex():
    assert _normalize_calldata("0x12345678") == "0x12345678"
    assert _normalize_calldata("0xABCDEF1200") == "0xabcdef1200"


def test_router_calldata_validation_fails_closed():
    with pytest.raises(ValueError, match="4-byte selector"):
        _normalize_calldata("0x12")
    with pytest.raises(ValueError, match="valid hex"):
        _normalize_calldata("0x1234567z")
    with pytest.raises(ValueError, match="0x-prefixed"):
        _normalize_calldata("12345678")


def test_unknown_semantic_selector_stays_unresolved():
    result = semantics.decode_router_calldata(chain="base", calldata="0x12345678")
    assert result.status == "UNSUPPORTED_ROUTER_SELECTOR"
    assert result.signature is None


def test_supported_selector_without_required_abi_head_fails_closed():
    selector = next(iter(semantics._SUPPORTED))
    result = semantics.decode_router_calldata(chain="base", calldata="0x" + selector)
    assert result.status == "MALFORMED_SUPPORTED_ROUTER_CALLDATA"
    assert result.amount_in is None
