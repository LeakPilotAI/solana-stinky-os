"""Canonical mint identity and alert idempotency.

One logical candidate / alert / Discord DM per mint.
Repeated event delivery must not double-count metrics or send 2 DMs.
"""

from __future__ import annotations

import re
from typing import Iterable

# Solana base58 mint (32-44 chars). Case-sensitive.
_MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

ALERT_CANDIDATE_PREFIX = "alert_candidate:"


def canonical_mint(raw: str | None) -> str | None:
    """Return the unique mint identity, or None if invalid."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # Reject whitespace / URL pollution
    if any(c in s for c in (" ", "\n", "\t", "/", "?", "#")):
        return None
    return s


def is_valid_mint(raw: str | None) -> bool:
    s = canonical_mint(raw)
    if not s:
        return False
    return bool(_MINT_RE.match(s))


def alert_candidate_key(mint: str | None) -> str | None:
    """Deterministic idempotency key: alert_candidate:{mint}."""
    m = canonical_mint(mint)
    if not m:
        return None
    return f"{ALERT_CANDIDATE_PREFIX}{m}"


class UniqueMintIndex:
    """In-memory unique-mint set for candidate / backtest / alert windows."""

    def __init__(self, initial: Iterable[str] | None = None) -> None:
        self._seen: set[str] = set()
        if initial:
            for mint in initial:
                self.add(mint)

    def add(self, mint: str | None) -> bool:
        """Insert mint. Returns True iff this is the first observation."""
        m = canonical_mint(mint)
        if not m:
            return False
        if m in self._seen:
            return False
        self._seen.add(m)
        return True

    def has(self, mint: str | None) -> bool:
        m = canonical_mint(mint)
        return bool(m) and m in self._seen

    def __len__(self) -> int:
        return len(self._seen)

    def mints(self) -> frozenset[str]:
        return frozenset(self._seen)


class AlertLedger:
    """One logical alert per mint. Duplicate delivery is a no-op."""

    def __init__(self) -> None:
        self._keys: set[str] = set()
        self.delivered: int = 0
        self.duplicates: int = 0

    def try_record(self, mint: str | None) -> tuple[bool, str | None]:
        key = alert_candidate_key(mint)
        if key is None:
            return False, None
        if key in self._keys:
            self.duplicates += 1
            return False, key
        self._keys.add(key)
        self.delivered += 1
        return True, key

    def has(self, mint: str | None) -> bool:
        key = alert_candidate_key(mint)
        return bool(key) and key in self._keys

    def __len__(self) -> int:
        return len(self._keys)
