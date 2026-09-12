"""Canonical chain registry for Genesis multi-chain intelligence.

This module is intentionally read-only. Adding a chain here does not authorize
trading or copy Solana admission thresholds onto another network.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ChainFamily(str, Enum):
    SOLANA = "solana"
    EVM = "evm"


@dataclass(frozen=True, slots=True)
class ChainConfig:
    key: str
    family: ChainFamily
    chain_id: int | None
    native_gas: str
    rpc_env: str | None
    default_rpc_url: str | None
    paper_only: bool = True
    live_execution_enabled: bool = False


CHAINS: dict[str, ChainConfig] = {
    "solana": ChainConfig(
        key="solana",
        family=ChainFamily.SOLANA,
        chain_id=None,
        native_gas="SOL",
        rpc_env="SOLANA_RPC_URL",
        default_rpc_url=None,
        paper_only=False,
        live_execution_enabled=False,
    ),
    "robinhood": ChainConfig(
        key="robinhood",
        family=ChainFamily.EVM,
        chain_id=4663,
        native_gas="ETH",
        rpc_env="ROBINHOOD_CHAIN_RPC_URL",
        default_rpc_url="https://rpc.mainnet.chain.robinhood.com",
        paper_only=True,
        live_execution_enabled=False,
    ),
    "base": ChainConfig(
        key="base",
        family=ChainFamily.EVM,
        chain_id=8453,
        native_gas="ETH",
        rpc_env="BASE_RPC_URL",
        default_rpc_url="https://mainnet.base.org",
        paper_only=True,
        live_execution_enabled=False,
    ),
}


def get_chain(key: str | None) -> ChainConfig | None:
    if key is None:
        return None
    return CHAINS.get(str(key).strip().lower())


def is_supported_chain(key: str | None) -> bool:
    return get_chain(key) is not None


def live_execution_allowed(key: str | None) -> bool:
    """Fail closed: registry entries must explicitly opt into live execution."""
    chain = get_chain(key)
    return bool(chain and chain.live_execution_enabled)
