"""Fail-closed, read-only JSON-RPC primitives for Genesis EVM observation.

This module deliberately exposes only observation methods. It has no wallet,
signing, raw-transaction, or execution surface. Robinhood Chain and Base remain
paper-only regardless of RPC availability.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from typing import Any, Callable
from urllib import request

from .chains import ChainFamily, get_chain
from .multichain_identity import canonical_chain_address


class EvmRpcError(RuntimeError):
    """Raised when EVM evidence cannot be independently obtained or validated."""


@dataclass(frozen=True, slots=True)
class EvmRpcObservation:
    chain: str
    chain_id: int
    block_number: int
    rpc_url: str


Transport = Callable[[str, bytes, float], dict[str, Any]]


def _is_hex_data(value: Any, *, byte_count: int | None = None) -> bool:
    """EIP-1474 Data consists solely of complete hex bytes after 0x."""
    return (
        isinstance(value, str)
        and re.fullmatch(r"0x(?:[0-9a-fA-F]{2})*", value) is not None
        and (byte_count is None or len(value) == 2 + 2 * byte_count)
    )


def resolve_rpc_url(chain_key: str) -> str:
    chain = get_chain(chain_key)
    if chain is None or chain.family is not ChainFamily.EVM:
        raise EvmRpcError(f"unsupported EVM chain: {chain_key!r}")
    configured = os.getenv(chain.rpc_env or "", "").strip() if chain.rpc_env else ""
    url = configured or (chain.default_rpc_url or "")
    if not url.startswith("https://"):
        raise EvmRpcError(f"no trusted HTTPS RPC configured for {chain.key}")
    return url


def _urllib_transport(url: str, payload: bytes, timeout: float) -> dict[str, Any]:
    req = request.Request(url, data=payload, headers={"Content-Type": "application/json", "User-Agent": "genesis-readonly/1"}, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - registry-controlled URL
            body = response.read()
    except Exception as exc:
        raise EvmRpcError(f"RPC request failed: {type(exc).__name__}") from exc
    try:
        decoded = json.loads(body)
    except (TypeError, ValueError) as exc:
        raise EvmRpcError("RPC returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise EvmRpcError("RPC returned non-object response")
    return decoded


class EvmReadOnlyRpc:
    """Minimal EVM observer with mandatory chain-ID attestation."""

    _ALLOWED_METHODS = frozenset({"eth_chainId", "eth_blockNumber", "eth_getBlockByNumber", "eth_getLogs", "eth_getCode", "eth_call", "eth_getStorageAt"})

    def __init__(self, chain_key: str, *, timeout: float = 5.0, transport: Transport | None = None) -> None:
        chain = get_chain(chain_key)
        if chain is None or chain.family is not ChainFamily.EVM or chain.chain_id is None:
            raise EvmRpcError(f"unsupported EVM chain: {chain_key!r}")
        if timeout <= 0 or timeout > 30:
            raise ValueError("timeout must be > 0 and <= 30 seconds")
        self.chain = chain
        self.rpc_url = resolve_rpc_url(chain.key)
        self.timeout = float(timeout)
        self._transport = transport or _urllib_transport
        self._next_id = 1

    def _call(self, method: str, params: list[Any] | None = None) -> Any:
        if method not in self._ALLOWED_METHODS:
            raise EvmRpcError(f"RPC method not allowed in read-only client: {method}")
        rpc_id = self._next_id
        self._next_id += 1
        payload = json.dumps({"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params or []}, separators=(",", ":")).encode("utf-8")
        response = self._transport(self.rpc_url, payload, self.timeout)
        if response.get("jsonrpc") != "2.0" or response.get("id") != rpc_id:
            raise EvmRpcError("RPC response envelope mismatch")
        if response.get("error") is not None:
            raise EvmRpcError(f"RPC returned error for {method}")
        if "result" not in response:
            raise EvmRpcError(f"RPC result missing for {method}")
        return response["result"]

    @staticmethod
    def _hex_int(value: Any, field: str) -> int:
        # EIP-1474 Quantity: minimal hex digits, with zero represented as 0x0.
        # Python int() alone also accepts whitespace and digit separators.
        if not isinstance(value, str) or re.fullmatch(r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)", value) is None:
            raise EvmRpcError(f"invalid {field} response")
        return int(value, 16)

    def attest_chain(self) -> int:
        observed = self._hex_int(self._call("eth_chainId"), "chain id")
        if observed != self.chain.chain_id:
            raise EvmRpcError(f"chain ID mismatch for {self.chain.key}: expected {self.chain.chain_id}, got {observed}")
        return observed

    def block_number(self) -> int:
        self.attest_chain()
        return self._hex_int(self._call("eth_blockNumber"), "block number")

    def observe_head(self) -> EvmRpcObservation:
        chain_id = self.attest_chain()
        block_number = self._hex_int(self._call("eth_blockNumber"), "block number")
        return EvmRpcObservation(self.chain.key, chain_id, block_number, self.rpc_url)

    def get_block_by_number(self, block_number: int) -> dict[str, Any]:
        if block_number < 0:
            raise ValueError("block_number must be non-negative")
        self.attest_chain()
        result = self._call("eth_getBlockByNumber", [hex(block_number), False])
        if not isinstance(result, dict):
            raise EvmRpcError("invalid block response")
        observed_number = self._hex_int(result.get("number"), "block number")
        block_hash = result.get("hash")
        if observed_number != block_number:
            raise EvmRpcError(f"block number mismatch: expected {block_number}, got {observed_number}")
        if not _is_hex_data(block_hash, byte_count=32):
            raise EvmRpcError("invalid block hash")
        return result

    def get_logs_for_block(
        self, block_hash: str, *, expected_block_number: int | None = None,
    ) -> list[dict[str, Any]]:
        if not _is_hex_data(block_hash, byte_count=32):
            raise ValueError("block_hash must be a 32-byte hex hash")
        if expected_block_number is not None and (
            type(expected_block_number) is not int or expected_block_number < 0
        ):
            raise ValueError("expected_block_number must be a non-negative integer")
        self.attest_chain()
        result = self._call("eth_getLogs", [{"blockHash": block_hash}])
        if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
            raise EvmRpcError("invalid logs response")
        seen_indices: set[int] = set()
        for item in result:
            if item.get("blockHash") != block_hash:
                raise EvmRpcError("log block hash mismatch")
            if not _is_hex_data(item.get("address"), byte_count=20):
                raise EvmRpcError("invalid log address")
            if not _is_hex_data(item.get("transactionHash"), byte_count=32):
                raise EvmRpcError("invalid log transaction hash")
            number = self._hex_int(item.get("blockNumber"), "log block number")
            if expected_block_number is not None and number != expected_block_number:
                raise EvmRpcError("log block number mismatch")
            index = self._hex_int(item.get("logIndex"), "log index")
            self._hex_int(item.get("transactionIndex"), "log transaction index")
            if index in seen_indices:
                raise EvmRpcError("duplicate log index in provider response")
            seen_indices.add(index)
            if item.get("removed") is not False:
                raise EvmRpcError("historical log must be explicitly nonremoved")
            if not _is_hex_data(item.get("data")):
                raise EvmRpcError("invalid log data")
            topics = item.get("topics")
            if not isinstance(topics, list) or any(not _is_hex_data(topic, byte_count=32) for topic in topics):
                raise EvmRpcError("invalid log topics")
        return result

    def call_at_block(self, address: str, data: str, block_number: int) -> str:
        canonical = canonical_chain_address(self.chain.key, address)
        if canonical is None:
            raise ValueError("address must be a valid address for this chain")
        if block_number < 0:
            raise ValueError("block_number must be non-negative")
        if not _is_hex_data(data) or len(data) < 10:
            raise ValueError("data must be even-length hex calldata with a selector")
        self.attest_chain()
        result = self._call("eth_call", [{"to": canonical, "data": data.lower()}, hex(block_number)])
        if not _is_hex_data(result):
            raise EvmRpcError("invalid eth_call response")
        return result.lower()

    def storage_at_block(self, address: str, slot: str, block_number: int) -> str:
        """Read one 32-byte storage word pinned to an explicit historical block."""
        canonical = canonical_chain_address(self.chain.key, address)
        if canonical is None:
            raise ValueError("address must be a valid address for this chain")
        if block_number < 0:
            raise ValueError("block_number must be non-negative")
        if not _is_hex_data(slot, byte_count=32):
            raise ValueError("slot must be a 32-byte hex storage key")
        self.attest_chain()
        result = self._call("eth_getStorageAt", [canonical, slot.lower(), hex(block_number)])
        if not _is_hex_data(result, byte_count=32):
            raise EvmRpcError("invalid eth_getStorageAt response")
        return result.lower()
