from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.chains import ChainFamily, get_chain, live_execution_allowed
from stinky_core.multichain_identity import asset_key, canonical_chain_address, wallet_key


def test_robinhood_chain_is_evm_4663_and_paper_only():
    chain = get_chain("robinhood")
    assert chain is not None
    assert chain.family is ChainFamily.EVM
    assert chain.chain_id == 4663
    assert chain.native_gas == "ETH"
    assert chain.paper_only is True
    assert live_execution_allowed("robinhood") is False


def test_base_is_evm_8453_and_paper_only():
    chain = get_chain("base")
    assert chain is not None
    assert chain.family is ChainFamily.EVM
    assert chain.chain_id == 8453
    assert chain.native_gas == "ETH"
    assert chain.paper_only is True
    assert live_execution_allowed("base") is False


def test_evm_identity_is_chain_scoped_and_case_normalized():
    address = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
    assert asset_key("base", address) == "base:0xabcdef0123456789abcdef0123456789abcdef01"
    assert asset_key("robinhood", address) == "robinhood:0xabcdef0123456789abcdef0123456789abcdef01"
    assert asset_key("base", address) != asset_key("robinhood", address)
    assert wallet_key("base", address) == asset_key("base", address)


def test_invalid_or_unknown_addresses_fail_closed():
    assert canonical_chain_address("base", "0x123") is None
    assert canonical_chain_address("robinhood", "https://bad") is None
    assert asset_key("unknown", "0xabcdef0123456789abcdef0123456789abcdef01") is None
    assert live_execution_allowed("unknown") is False


def test_solana_identity_remains_case_sensitive_and_chain_scoped():
    mint = "So11111111111111111111111111111111111111112"
    assert asset_key("solana", mint) == f"solana:{mint}"
