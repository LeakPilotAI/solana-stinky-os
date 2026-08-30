"""Canonical pool / program exclusion.

These addresses must never contaminate:
  early buyers, smart money, wallet performance, entities, patterns, score, alerts.
"""

from __future__ import annotations

EXCLUDED_POOLS_AND_PROGRAMS: frozenset[str] = frozenset(
    {
        # System / token programs
        "11111111111111111111111111111111",
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
        "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
        "ComputeBudget111111111111111111111111111111",
        "SysvarRent111111111111111111111111111111111",
        "SysvarC1ock11111111111111111111111111111111",
        # Pump.fun
        "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
        "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
        "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg",
        # Raydium
        "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
        "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
        "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
        # Jupiter
        "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
        "JUP4Fb2cqiRUcaTHdrLCGBKqKghvh9j8sH4k6b3p5s1",
        # Orca / Meteora / common AMMs
        "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
        "9W959DqEETiSZqfCJHNhSbiGq3uXEbJQyrT7T6kTqFMw",
        "Eo7WjKq67rjJ4q7rxQ8Lv3hLaeGdsA1z4Qw5TWkFGN5",
        "LBUZKhRxPF3XUpBCjp4YzTKgLccasB3Lz8ZqiTwGbQ",
        "cpamdpZCGKUy5JxQXB4dcpGUSFkNMfms7dwjbGRqAfJ",
    }
)


def is_excluded_pool_or_program(address: str | None) -> bool:
    if not address:
        return True
    return address.strip() in EXCLUDED_POOLS_AND_PROGRAMS


def is_rankable_wallet(address: str | None) -> bool:
    """Human-wallet heuristic: valid length and not a known program/pool."""
    if not address:
        return False
    s = address.strip()
    if len(s) < 32:
        return False
    return s not in EXCLUDED_POOLS_AND_PROGRAMS
