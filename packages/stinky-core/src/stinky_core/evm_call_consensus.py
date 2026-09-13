"""Pure helpers for fail-closed exact-result consensus."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ExactResultConsensus:
    agreed_result: str | None
    providers: tuple[str, ...]
    verdict: str


def classify_exact_results(
    result_providers: Mapping[str, tuple[str, ...] | list[str]],
    *,
    min_quorum: int = 2,
) -> ExactResultConsensus:
    if min_quorum < 2:
        raise ValueError("min_quorum must be at least 2")

    normalized: dict[str, tuple[str, ...]] = {}
    for result, providers in result_providers.items():
        unique = tuple(sorted(set(providers)))
        if unique:
            normalized[result] = unique

    qualifying = [(result, providers) for result, providers in normalized.items() if len(providers) >= min_quorum]
    if len(qualifying) == 1 and len(normalized) == 1:
        result, providers = qualifying[0]
        return ExactResultConsensus(result, providers, "EXACT_RESULT_QUORUM")
    if len(normalized) > 1:
        return ExactResultConsensus(None, (), "RESULT_DISAGREEMENT")
    return ExactResultConsensus(None, (), "INSUFFICIENT_RESULT_EVIDENCE")
