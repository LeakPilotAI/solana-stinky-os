"""Fail-closed, read-only JSON-RPC primitives for Genesis EVM observation.

This module deliberately exposes only observation methods. It has no wallet,
signing, raw-transaction, or execution surface. Robinhood Chain and Base remain
paper-only regardless of RPC availability.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
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
    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "genesis-readonly/1"},
        method="POST",
    )
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

    _ALLOWED_METHODS = frozenset(
        {
            "eth_chainId",
            "eth_blockNumber",
            "eth_getBlockByNumber",
            "eth_getLogs",
            "eth_getCode",
            "eth_call",
        }
    )

    def __init__(
        self,
        chain_key: str,
        *,
        timeout: float = 5.0,
        transport: Transport | None = None,
    ) -> None:
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
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params or []},
            separators=(",", ":"),
        ).encode("utf-8")
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
        if not isinstance(value, str) or not value.startswith("0x"):
            raise EvmRpcError(f"invalid {field} response")
        try:
            return int(value, 16)
        except ValueError as exc:
            raise EvmRpcError(f"invalid {field} response") from exc

    def attest_chain(self) -> int:
        observed = self._hex_int(self._call("eth_chainId"), "chain id")
        if observed != self.chain.chain_id:
            raise EvmRpcError(
                f"chain ID mismatch for {self.chain.key}: expected {self.chain.chain_id}, got {observed}"
            )
        return observed

    def block_number(self) -> int:
        self.attest_chain()
        return self._hex_int(self._call("eth_blockNumber"), "block number")

    def observe_head(self) -> EvmRpcObservation:
        chain_id = self.attest_chain()
        block_number = self._hex_int(self._call("eth_blockNumber"), "block number")
        return EvmRpcObservation(
            chain=self.chain.key,
            chain_id=chain_id,
            block_number=block_number,
            rpc_url=self.rpc_url,
        )

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
            raise EvmRpcError(
                f"block number mismatch: expected {block_number}, got {observed_number}"
            )
        if not isinstance(block_hash, str) or not block_hash.startswith("0x") or len(block_hash) != 66:
            raise EvmRpcError("invalid block hash")
        return result

    def get_logs_for_block(self, block_hash: str) -> list[dict[str, Any]]:
        if not isinstance(block_hash, str) or not block_hash.startswith("0x") or len(block_hash) != 66:
            raise ValueError("block_hash must be a 32-byte hex hash")
        self.attest_chain()
        result = self._call("eth_getLogs", [{"blockHash": block_hash}])
        if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
            raise EvmRpcError("invalid logs response")
        for item in result:
            if item.get("blockHash") != block_hash:
                raise EvmRpcError("log block hash mismatch")
        return result

    def call_at_block(self, address: str, data: str, block_number: int) -> str:
        """Perform one read-only eth_call pinned to an explicit historical block."""
        canonical = canonical_chain_address(self.chain.key, address)
        if canonical is None:
            raise ValueError("address must be a valid address for this chain")
        if block_number < 0:
            raise ValueError("block_number must be non-negative")
        if not isinstance(data, str) or not data.startswith("0x") or len(data) < 10 or len(data) % 2:
            raise ValueError("data must be even-length hex calldata with a selector")
        try:
            int(data[2:], 16)
        except ValueError as exc:
            raise ValueError("data must be hex calldata") from exc
        self.attest_chain()
        result = self._call("eth_call", [{"to": canonical, "data": data.lower()}, hex(block_number)])
        if not isinstance(result, str) or not result.startswith("0x") or len(result) % 2:
            raise EvmRpcError("invalid eth_call response")
        try:
            int(result[2:] or "0", 16)
        except ValueError as exc:
            raise EvmRpcError("invalid eth_call response") from exc
        return result.lower()
