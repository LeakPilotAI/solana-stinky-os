"""Chain-scoped identities for Solana and EVM observations.

Legacy Solana mint identity remains untouched. New multi-chain code must use
these keys so identical address text on different chains cannot collide.
"""

from __future__ import annotations

import re

from .chains import ChainFamily, get_chain

_EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_SOLANA_ADDRESS_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def canonical_chain_address(chain: str | None, raw: str | None) -> str | None:
    cfg = get_chain(chain)
    if cfg is None or raw is None:
        return None
    value = str(raw).strip()
    if not value or any(c in value for c in (" ", "\n", "\t", "/", "?", "#")):
        return None
    if cfg.family is ChainFamily.EVM:
        if not _EVM_ADDRESS_RE.fullmatch(value):
            return None
        return value.lower()
    if cfg.family is ChainFamily.SOLANA:
        if not _SOLANA_ADDRESS_RE.fullmatch(value):
            return None
        return value
    return None


def chain_scoped_key(chain: str | None, raw: str | None) -> str | None:
    cfg = get_chain(chain)
    address = canonical_chain_address(chain, raw)
    if cfg is None or address is None:
        return None
    return f"{cfg.key}:{address}"


def asset_key(chain: str | None, raw: str | None) -> str | None:
    return chain_scoped_key(chain, raw)


def wallet_key(chain: str | None, raw: str | None) -> str | None:
    return chain_scoped_key(chain, raw)
