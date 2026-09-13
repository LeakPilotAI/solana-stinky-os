"""Conservative semantic decoding for supported historical EVM router-call evidence."""
from __future__ import annotations

from dataclasses import dataclass


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
