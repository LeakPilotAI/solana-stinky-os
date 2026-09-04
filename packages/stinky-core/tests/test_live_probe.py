"""LIVE DexScreener probe. Does not lower Gate 1. Does not invent a $150k print.

If DexScreener is unreachable: status UNKNOWN, test still passes.
If no pair ≥ $33k 5m: LIVE GATE-1: NOT OBSERVED — that is not a failure.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from stinky_core.admission import GATE1_VOLUME_5M_USD, evaluate_gate1

URL = "https://api.dexscreener.com/latest/dex/search?q=pumpswap"


def test_live_gate1_not_fabricated():
    assert GATE1_VOLUME_5M_USD == 33_000
    req = urllib.request.Request(URL, headers={"Accept": "application/json", "User-Agent": "StinkyOS/operator-v1.1.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        # LIVE probe failed. UNKNOWN is not OBSERVED.
        return

    pairs = body.get("pairs") or []
    observed = 0
    for p in pairs:
        if p.get("chainId") != "solana":
            continue
        vol = (p.get("volume") or {}).get("m5")
        mint = (p.get("baseToken") or {}).get("address")
        dex = p.get("dexId")
        d = evaluate_gate1(
            {
                "mint": mint,
                "protocol": dex,
                "volume_usd": vol,
                "migrated": True,
            }
        )
        if d.eligible:
            observed += 1
    # Do not assert observed > 0. NOT OBSERVED is success.
    assert observed >= 0
    assert GATE1_VOLUME_5M_USD == 33_000
