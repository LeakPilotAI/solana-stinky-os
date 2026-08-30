"""Intelligence book: ledgers, time-machine as-of, outcome-from-later-ticks.

Does not replace IntelligenceMemory. Queries the same as-of store.
Never fabricates wallets, fees, identities, or probabilities.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from stinky_core.intelligence import (
    INTEL_VERSION,
    information_advantage,
    investigate,
    why_this_ca,
)
from stinky_core.memory import IntelligenceMemory, _before, _parse_ts
from stinky_core.outcomes import DEFAULT_OBSERVATION_WINDOW_SEC, LABEL_VERSION, label_outcome

BOOK_VERSION = "book-v1.1.0-recognition"
LIFE_SLICES_SEC = (0, 30, 60, 120, 180, 300, 600)


def wallet_book(memory: IntelligenceMemory, *, as_of: Any = None) -> list[dict[str, Any]]:
    wallets = sorted({o.wallet for o in memory.wallet_obs})
    perf = memory.wallet_performance_as_of(wallets, as_of=as_of)
    rows = [{"wallet": w, **perf[w]} for w in sorted(perf)]
    rows.sort(key=lambda r: (-(r.get("sample_resolved") or 0), -(r.get("runners") or 0), r["wallet"]))
    return rows


def creator_book(memory: IntelligenceMemory, *, as_of: Any = None) -> list[dict[str, Any]]:
    creators = sorted({o.wallet for o in memory.creator_obs})
    out: list[dict[str, Any]] = []
    for c in creators:
        p = memory.creator_profile_as_of(c, as_of=as_of)
        if p:
            out.append({"creator": c, **p})
    out.sort(key=lambda r: (-(r.get("launch_count") or 0), r["creator"]))
    return out


def pattern_book(memory: IntelligenceMemory, *, as_of: Any = None, min_sample: int = 5) -> list[dict[str, Any]]:
    cutoff = _parse_ts(as_of)
    keys = sorted({r.fingerprint for r in memory.fingerprints})
    rows: list[dict[str, Any]] = []
    for fp in keys:
        hit = memory.pattern_match_as_of(fp, as_of=as_of, min_sample=min_sample)
        last = max(
            (r.observed_at for r in memory.fingerprints if r.fingerprint == fp and _before(r.observed_at, cutoff)),
            default=None,
        )
        rows.append({
            "fingerprint": fp,
            "occurrences": hit.get("sample_count") or 0,
            "resolved": (hit.get("runner_matches") or 0) + (hit.get("held_matches") or 0) + (hit.get("fade_matches") or 0),
            "runners": hit.get("runner_matches") or 0,
            "held": hit.get("held_matches") or 0,
            "fades": hit.get("fade_matches") or 0,
            "unknown": hit.get("unknown_matches") or 0,
            "runner_fraction": (
                (hit.get("runner_matches") or 0)
                / max(1, (hit.get("runner_matches") or 0) + (hit.get("held_matches") or 0) + (hit.get("fade_matches") or 0))
                if ((hit.get("runner_matches") or 0) + (hit.get("held_matches") or 0) + (hit.get("fade_matches") or 0))
                else None
            ),
            "confidence": hit.get("confidence"),
            "runner_pattern": bool(hit.get("runner_pattern")),
            "fade_pattern": bool(hit.get("fade_pattern")),
            "last_seen": last.isoformat() if last else None,
            "calibrated_probability": False,
        })
    rows.sort(key=lambda r: (-r["occurrences"], r["fingerprint"]))
    return rows


def book_stats(memory: IntelligenceMemory, *, as_of: Any = None, exclude_mint: str | None = None) -> dict[str, Any]:
    cutoff = _parse_ts(as_of)
    exclude = (exclude_mint or "").strip()

    def vis(ts: datetime) -> bool:
        return _before(ts, cutoff)

    w_obs = [o for o in memory.wallet_obs if vis(o.observed_at) and o.mint != exclude]
    c_obs = [o for o in memory.creator_obs if vis(o.observed_at) and o.mint != exclude]
    fps = [o for o in memory.fingerprints if vis(o.observed_at) and o.mint != exclude]
    w_out = [o for o in memory.wallet_outcomes if vis(o.labeled_at) and o.mint != exclude]
    resolved = [o for o in w_out if o.label in ("RUNNER", "HELD", "FADE")]
    ticks = [o for o in getattr(memory, "market_ticks", []) if vis(o.observed_at) and o.mint != exclude]
    unique_mints = {o.mint for o in fps} | {o.mint for o in w_obs} | {d.get("mint") for d in memory.decisions if d.get("mint")}
    if exclude:
        unique_mints.discard(exclude)
    return {
        "book_version": BOOK_VERSION,
        "memory_version": memory.version,
        "intel_version": INTEL_VERSION,
        "as_of": cutoff.isoformat() if cutoff else None,
        "unique_mints": len(unique_mints),
        "wallet_observations": len(w_obs),
        "unique_wallets": len({o.wallet for o in w_obs}),
        "creator_observations": len(c_obs),
        "unique_creators": len({o.wallet for o in c_obs}),
        "fingerprints": len(fps),
        "unique_fingerprints": len({o.fingerprint for o in fps}),
        "wallet_outcomes": len(w_out),
        "resolved_outcomes": len(resolved),
        "market_ticks": len(ticks),
        "intelligence_decisions": len([d for d in memory.decisions if d.get("mint") != exclude]),
        "coverage": {
            "wallets": "OBSERVED" if w_obs else "UNKNOWN",
            "creators": "OBSERVED" if c_obs else "UNKNOWN",
            "patterns": "OBSERVED" if fps else "UNKNOWN",
            "outcomes": "OBSERVED" if resolved else "UNKNOWN",
        },
        "calibrated_probability": False,
    }


def outcome_from_ticks(
    memory: IntelligenceMemory,
    *,
    mint: str,
    decision_at: Any,
    observation_window: float = DEFAULT_OBSERVATION_WINDOW_SEC,
    now: Any = None,
) -> dict[str, Any]:
    """Label from post-decision market ticks only. Missing ticks → UNKNOWN."""
    start = _parse_ts(decision_at)
    if start is None:
        oc = label_outcome(observation_complete=False)
        return oc.to_dict()
    horizon = start + timedelta(seconds=float(observation_window or DEFAULT_OBSERVATION_WINDOW_SEC))
    end = _parse_ts(now) or datetime.now(timezone.utc)
    ticks = [
        t for t in getattr(memory, "market_ticks", [])
        if t.mint == mint and t.observed_at > start
    ]
    if not ticks:
        oc = label_outcome(
            decision_timestamp=start.isoformat(),
            observation_complete=False,
            observation_window=observation_window,
        )
        d = oc.to_dict()
        d["outcome_timestamp"] = None
        d["observation_timestamps"] = []
        return d
    vols = [t.volume_m5_usd for t in ticks if t.volume_m5_usd is not None]
    prices = [t.price_usd for t in ticks if t.price_usd is not None]
    entry = next(
        (t for t in sorted(getattr(memory, "market_ticks", []), key=lambda x: x.observed_at)
         if t.mint == mint and t.observed_at <= start),
        None,
    )
    entry_vol = entry.volume_m5_usd if entry else None
    entry_px = entry.price_usd if entry else None
    peak_vol = max(vols) if vols else None
    peak_px = max(prices) if prices else None
    multiple = None
    if entry_px and peak_px and entry_px > 0:
        multiple = peak_px / entry_px
    elif entry_vol and peak_vol and entry_vol > 0:
        multiple = peak_vol / entry_vol
    complete = end >= horizon or len(ticks) >= 3
    oc = label_outcome(
        peak_multiple=multiple,
        peak_volume=peak_vol,
        entry_volume=entry_vol,
        entry_price=entry_px,
        decision_timestamp=start.isoformat(),
        observation_window=observation_window,
        observation_complete=complete,
    )
    d = oc.to_dict()
    d["outcome_timestamp"] = max(t.observed_at for t in ticks).isoformat()
    d["observation_timestamps"] = [t.observed_at.isoformat() for t in sorted(ticks, key=lambda x: x.observed_at)]
    d["peak_price_usd"] = peak_px
    d["label_version"] = LABEL_VERSION
    return d


def time_machine(
    *,
    mint: str,
    as_of: Any,
    bundle: Mapping[str, Any] | None = None,
    memory: IntelligenceMemory,
) -> dict[str, Any]:
    """What would Stinky have known at Gate 1. Future labels are hidden."""
    payload = dict(bundle or {})
    payload["mint"] = mint
    payload["decision_timestamp"] = as_of if isinstance(as_of, str) else (
        as_of.isoformat() if hasattr(as_of, "isoformat") else as_of
    )
    inv = investigate(payload, memory=memory)
    wallets = payload.get("buyers") if isinstance(payload.get("buyers"), list) else []
    wallet_ids = [str(b.get("wallet") or b.get("userAddress") or "").strip() for b in wallets]
    wallet_ids = [w for w in wallet_ids if w]
    return {
        "book_version": BOOK_VERSION,
        "mint": mint,
        "as_of": payload["decision_timestamp"],
        "future_hidden": True,
        "investigation": inv.to_dict(),
        "why": why_this_ca(inv),
        "information_advantage": information_advantage(inv),
        "book": book_stats(memory, as_of=as_of, exclude_mint=mint),
        "known_then": {
            "wallets": memory.wallet_performance_as_of(wallet_ids, as_of=as_of, exclude_mint=mint) if wallet_ids else {},
            "creator": memory.creator_profile_as_of(payload.get("creator"), as_of=as_of, exclude_mint=mint),
            "patterns": memory.pattern_match_as_of(inv.fingerprint, as_of=as_of, exclude_mint=mint),
            "entities": memory.relationships_as_of(wallet_ids, as_of=as_of, exclude_mint=mint) if wallet_ids else {"status": "UNKNOWN", "links": [], "link_count": 0},
        },
        "calibrated_probability": False,
        "note": "As-of only. This mint's own later outcome is not visible here.",
    }


def life_slices(
    memory: IntelligenceMemory,
    *,
    mint: str,
    t0: Any,
    as_of: Any = None,
) -> dict[str, Any]:
    """Market path at T+ offsets. Wallet/creator stay the T+0 as-of snapshot.

    Future ticks after `as_of` are hidden. Missing offsets stay UNKNOWN.
    """
    start = _parse_ts(t0)
    cutoff = _parse_ts(as_of)
    if start is None:
        return {
            "mint": mint,
            "t0": None,
            "slices": [],
            "calibrated_probability": False,
            "note": "decision timestamp UNKNOWN",
        }

    def visible(ts) -> bool:
        if ts < start:
            return False
        if cutoff is None:
            return True
        if ts < cutoff:
            return True
        return ts == start == cutoff

    t0_ticks = [
        t for t in getattr(memory, "market_ticks", [])
        if t.mint == mint and t.observed_at == start
    ]
    base_vol = t0_ticks[0].volume_m5_usd if t0_ticks else None
    slices: list[dict[str, Any]] = []
    for offset in LIFE_SLICES_SEC:
        horizon = start + timedelta(seconds=int(offset))
        chosen = None
        for t in sorted(
            (x for x in getattr(memory, "market_ticks", []) if x.mint == mint),
            key=lambda x: x.observed_at,
        ):
            if not visible(t.observed_at):
                continue
            if t.observed_at > horizon:
                continue
            chosen = t
        vol = chosen.volume_m5_usd if chosen else None
        accel = None
        if offset and base_vol is not None and vol is not None:
            accel = round((vol - base_vol) / offset, 6)
        slices.append({
            "offset_sec": offset,
            "label": f"T+{offset}s" if offset else "T+0",
            "observed_at": chosen.observed_at.isoformat() if chosen else None,
            "volume_m5_usd": vol,
            "price_usd": chosen.price_usd if chosen else None,
            "liquidity_usd": chosen.liquidity_usd if chosen else None,
            "volume_acceleration": accel,
            "source": chosen.source if chosen else None,
            "missing": [] if chosen else ["market_tick"],
        })
    return {
        "book_version": BOOK_VERSION,
        "mint": mint,
        "t0": start.isoformat(),
        "as_of": cutoff.isoformat() if cutoff else None,
        "future_hidden": True,
        "slices": slices,
        "wallet_quality": "T+0 as-of only — later buyers do not leak backward",
        "calibrated_probability": False,
        "note": "Wallet/creator/pattern intelligence is the T+0 snapshot. T+ slices are market ticks only.",
    }
