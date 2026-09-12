"""Temporal-safe wallet history bridge for prospective re-evaluation.

Core intelligence memory remains authoritative. During a single prospective
re-evaluation, durable wallet_performance rows explicitly loaded as-of the
current decision may fill fields that are absent from memory. Existing memory
values are never overwritten, and the overlay is removed immediately after the
re-evaluation completes.
"""
from __future__ import annotations

from typing import Any, Mapping

from sentinel.reevaluation import ReevaluatingVolumeMonitor


class _FieldMergeMemory:
    """Delegate memory while filling only missing wallet-history fields."""

    def __init__(self, base: Any, overlay: Mapping[str, Mapping[str, Any]]) -> None:
        self._base = base
        self._overlay = {str(k): dict(v) for k, v in overlay.items()}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)

    def wallet_performance_as_of(
        self,
        wallet_ids: list[str],
        *,
        as_of: Any,
        exclude_mint: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        base_rows = self._base.wallet_performance_as_of(
            wallet_ids,
            as_of=as_of,
            exclude_mint=exclude_mint,
        )
        merged: dict[str, dict[str, Any]] = {
            str(wallet): dict(row) for wallet, row in (base_rows or {}).items()
        }
        for wallet in wallet_ids:
            extra = self._overlay.get(str(wallet))
            if not extra:
                continue
            row = merged.setdefault(str(wallet), {})
            for field, value in extra.items():
                if field not in row or row.get(field) is None:
                    row[field] = value
        return merged


class TemporalWalletMergeVolumeMonitor(ReevaluatingVolumeMonitor):
    """Re-evaluator with one-call, field-level wallet history overlay."""

    async def _load_reevaluation_wallet_history(
        self, mint: str
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        buyers, perf = await super()._load_reevaluation_wallet_history(mint)
        base = getattr(self, "_memory", None)
        if base is not None and perf:
            self._memory = _FieldMergeMemory(base, perf)
        return buyers, perf

    async def _reevaluate_with_complete_wallet_history(self, migration, snap) -> bool:
        base = getattr(self, "_memory", None)
        try:
            return await super()._reevaluate_with_complete_wallet_history(migration, snap)
        finally:
            self._memory = base
