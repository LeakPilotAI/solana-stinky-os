from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

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
