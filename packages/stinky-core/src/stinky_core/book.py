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
from stinky_core.reputation import CREATOR_TIERS, WALLET_TIERS
from stinky_core.stages import STAGES_VERSION, slice_stage
from stinky_core.observation import (
    observation_book as _observation_book,
    what_happened_next as _what_happened_next,
)
from stinky_core.recipes import runner_recipe

BOOK_VERSION = "book-v1.4.0-quality"
LIFE_SLICES_SEC = (0, 15, 30, 60, 90, 120, 180, 300, 600, 900, 1200, 1800)


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
        buys = getattr(chosen, "buys", None) if chosen else None
        sells = getattr(chosen, "sells", None) if chosen else None
        ratio = None
        if buys is not None and sells is not None and (buys + sells) > 0:
            ratio = round(buys / (buys + sells), 4)
        slices.append({
            "offset_sec": offset,
            "label": f"T+{offset}s" if offset else "T+0",
            "observed_at": chosen.observed_at.isoformat() if chosen else None,
            "volume_m5_usd": vol,
            "price_usd": chosen.price_usd if chosen else None,
            "liquidity_usd": chosen.liquidity_usd if chosen else None,
            "market_cap_usd": getattr(chosen, "market_cap_usd", None) if chosen else None,
            "buys": buys,
            "sells": sells,
            "transaction_count": getattr(chosen, "txns", None) if chosen else None,
            "unique_buyers": getattr(chosen, "unique_buyers", None) if chosen else None,
            "unique_sellers": getattr(chosen, "unique_sellers", None) if chosen else None,
            "buy_sell_ratio": ratio,
            "volume_acceleration": accel,
            "source": chosen.source if chosen else None,
            "missing": [] if chosen else ["market_tick"],
            "stage": slice_stage(offset),
        })
    return {
        "book_version": BOOK_VERSION,
        "stages_version": STAGES_VERSION,
        "mint": mint,
        "t0": start.isoformat(),
        "as_of": cutoff.isoformat() if cutoff else None,
        "future_hidden": True,
        "slices": slices,
        "wallet_quality": "T+0 as-of only — later buyers do not leak backward",
        "calibrated_probability": False,
        "note": "Wallet/creator/pattern intelligence is the T+0 snapshot. T+ slices are market ticks only. Stages are labels, not a second engine.",
    }


def dataset_health(memory: IntelligenceMemory, *, as_of: Any = None, exclude_mint: str | None = None) -> dict[str, Any]:
    """Coverage of the accumulating book. Empty is empty. Never invented."""
    stats = book_stats(memory, as_of=as_of, exclude_mint=exclude_mint)
    wallets = wallet_book(memory, as_of=as_of)
    creators = creator_book(memory, as_of=as_of)
    patterns = pattern_book(memory, as_of=as_of, min_sample=1)
    w_tiers = {t: 0 for t in WALLET_TIERS}
    for w in wallets:
        tier = str((w.get("reputation") or {}).get("tier") or w.get("reputation_tier") or "OBSERVED")
        w_tiers[tier] = w_tiers.get(tier, 0) + 1
    c_tiers = {t: 0 for t in CREATOR_TIERS}
    for c in creators:
        tier = str((c.get("reputation") or {}).get("tier") or "UNKNOWN")
        c_tiers[tier] = c_tiers.get(tier, 0) + 1
    known_fp = [p for p in patterns if (p.get("occurrences") or 0) >= 1]
    historical = [p for p in patterns if (p.get("occurrences") or 0) >= 5]
    runner_ex = sum(int(p.get("runners") or 0) for p in patterns)
    fade_ex = sum(int(p.get("fades") or 0) for p in patterns)
    held_ex = sum(int(p.get("held") or 0) for p in patterns)
    unique = max(1, int(stats.get("unique_mints") or 0)) if stats.get("unique_mints") else 0
    denom = unique if unique else 0

    def pct(n: int) -> float | None:
        if not denom:
            return None
        return round(100.0 * n / denom, 1)

    wallet_cov_n = int(stats.get("unique_wallets") or 0)
    creator_cov_n = int(stats.get("unique_creators") or 0)
    outcome_n = int(stats.get("resolved_outcomes") or 0)
    fp_n = int(stats.get("unique_fingerprints") or 0)
    decisions = [
        d for d in memory.decisions
        if (not exclude_mint or d.get("mint") != exclude_mint)
    ]
    labeled = [d for d in decisions if (d.get("outcome_label") or "UNKNOWN") in ("RUNNER", "HELD", "FADE")]
    return {
        "book_version": BOOK_VERSION,
        "as_of": stats.get("as_of"),
        "investigated_tokens": int(stats.get("unique_mints") or 0),
        "resolved_outcomes": outcome_n,
        "unlabeled_outcomes": max(0, int(stats.get("unique_mints") or 0) - outcome_n),
        "wallets": dict(w_tiers),
        "wallet_count": len(wallets),
        "creators": dict(c_tiers),
        "creator_count": len(creators),
        "patterns": {
            "known_fingerprints": len(known_fp),
            "historical_matches": len(historical),
            "runner_examples": runner_ex,
            "fade_examples": fade_ex,
            "held_examples": held_ex,
        },
        "data_coverage": {
            "wallet_coverage": pct(wallet_cov_n) if denom else None,
            "creator_coverage": pct(creator_cov_n) if denom else None,
            "outcome_coverage": pct(len(labeled) if labeled else outcome_n) if denom else None,
            "fingerprint_coverage": pct(fp_n) if denom else None,
            "note": "Coverage is share of unique investigated mints with that layer. None = no mints yet.",
        },
        "labeled_vs_unlabeled": {
            "labeled": len(labeled) if labeled else outcome_n,
            "unlabeled": max(0, len(decisions) - (len(labeled) if labeled else 0)),
        },
        "warnings": _health_warnings(
            investigated=int(stats.get("unique_mints") or 0),
            runners=runner_ex,
            wallet_cov=pct(wallet_cov_n) if denom else None,
            creator_cov=pct(creator_cov_n) if denom else None,
            outcome_cov=pct(len(labeled) if labeled else outcome_n) if denom else None,
            fp_cov=pct(fp_n) if denom else None,
            historical=len(historical),
            unique=int(stats.get("unique_mints") or 0),
        ),
        "calibrated_probability": False,
        "recipe_readiness": int(stats.get("unique_mints") or 0) >= 20 and len(historical) >= 1,
        "analogue_readiness": len(historical) >= 1,
        "holdout_readiness": int(stats.get("unique_mints") or 0) >= 30,
        "quality_state_transitions": len(getattr(memory, "quality_states", []) or []),
        "observation_coverage": {
            "investigations": int(stats.get("unique_mints") or 0),
            "market_ticks": int(stats.get("market_ticks") or len(getattr(memory, "market_ticks", []) or [])),
        },
        "note": "This tells us whether Stinky is actually learning. Empty book is not a live sample.",
    }


def _health_warnings(
    *,
    investigated: int,
    runners: int,
    wallet_cov: float | None,
    creator_cov: float | None,
    outcome_cov: float | None,
    fp_cov: float | None,
    historical: int,
    unique: int,
) -> list[str]:
    out: list[str] = []
    if investigated == 0:
        out.append("No Gate 1 investigations stored yet.")
        return out
    if runners < 5:
        out.append(f"Only {runners} RUNNER labels exist.")
    if wallet_cov is not None and wallet_cov < 20:
        out.append(f"Wallet history exists for {wallet_cov}% of investigations.")
    if creator_cov is not None and creator_cov < 20:
        out.append(f"Creator history exists for {creator_cov}% of investigations.")
    if outcome_cov is not None and outcome_cov < 30:
        out.append(f"Resolved outcomes cover {outcome_cov}% of investigations.")
    if historical == 0:
        out.append("Historical similarity is unavailable (no fingerprint with sample ≥ 5).")
    if unique < 20:
        out.append(f"Sample size {unique} is too small to claim precision.")
    return out


def unknown_queue(memory: IntelligenceMemory, *, as_of: Any = None) -> list[dict[str, Any]]:
    """Gate 1 passed but evidence is insufficient. Research queue, not a disappear."""
    cutoff = _parse_ts(as_of)
    rows: list[dict[str, Any]] = []
    for d in memory.decisions:
        ts = _parse_ts(d.get("decision_timestamp"))
        if cutoff is not None and ts is not None and not _before(ts, cutoff) and ts != cutoff:
            continue
        status = str(d.get("pipeline_status") or "UNKNOWN")
        intel = bool(d.get("has_intelligence"))
        if status == "REJECTED":
            continue
        if intel and status in ("QUALIFIED", "ALERT", "HIGH_RISK"):
            continue
        rows.append({
            "mint": d.get("mint"),
            "decision_timestamp": d.get("decision_timestamp"),
            "volume_m5_usd": d.get("volume_m5_usd"),
            "pipeline_status": status,
            "has_intelligence": intel,
            "promote": bool(d.get("promote")),
            "reason": "INSUFFICIENT_EVIDENCE",
            "note": "UNKNOWN is a research queue, not a buy and not a hide.",
        })
    rows.sort(key=lambda r: str(r.get("decision_timestamp") or ""), reverse=True)
    return rows


def wallet_radar(memory: IntelligenceMemory, *, as_of: Any = None, min_tier: str = "DEVELOPING") -> list[dict[str, Any]]:
    """Wallets in the book with meaningful historical reputation. Empty is empty."""
    order = {"OBSERVED": 0, "DEVELOPING": 1, "MEASURED": 2, "STRONG": 3}
    floor = order.get(min_tier, 1)
    rows = []
    for w in wallet_book(memory, as_of=as_of):
        tier = str((w.get("reputation") or {}).get("tier") or w.get("reputation_tier") or "OBSERVED")
        if order.get(tier, 0) < floor:
            continue
        rows.append({
            "wallet": w.get("wallet"),
            "reputation": tier,
            "sample_resolved": w.get("sample_resolved"),
            "runners": w.get("runners"),
            "fades": w.get("fades"),
            "held": w.get("held"),
            "hit_rate": w.get("hit_rate"),
            "calibrated_probability": False,
        })
    return rows[:40]


def creator_radar(memory: IntelligenceMemory, *, as_of: Any = None) -> list[dict[str, Any]]:
    rows = []
    for c in creator_book(memory, as_of=as_of):
        launches = int(c.get("launch_count") or c.get("launches") or 0)
        if launches < 2:
            continue
        rows.append({
            "creator": c.get("creator"),
            "reputation": (c.get("reputation") or {}).get("tier") or "OBSERVED",
            "launches": launches,
            "runners": c.get("runners") or c.get("historical_runners"),
            "fades": c.get("fades") or c.get("historical_fades"),
            "serial_risk": "HIGH" if launches >= 15 else "LOW",
            "calibrated_probability": False,
        })
    return rows[:40]


def pattern_radar(memory: IntelligenceMemory, *, as_of: Any = None) -> list[dict[str, Any]]:
    rows = []
    for p in pattern_book(memory, as_of=as_of, min_sample=1):
        if (p.get("occurrences") or 0) < 2:
            continue
        rows.append({
            "fingerprint": p.get("fingerprint"),
            "occurrences": p.get("occurrences"),
            "runners": p.get("runners"),
            "fades": p.get("fades"),
            "held": p.get("held"),
            "confidence": p.get("confidence"),
            "runner_pattern": p.get("runner_pattern"),
            "fade_pattern": p.get("fade_pattern"),
            "calibrated_probability": False,
        })
    return rows[:40]


def desk_snapshot(memory: IntelligenceMemory, *, as_of: Any = None) -> dict[str, Any]:
    """Command Center payload from the book. Empty radars stay empty."""
    return {
        "book_version": BOOK_VERSION,
        "stats": book_stats(memory, as_of=as_of),
        "dataset_health": dataset_health(memory, as_of=as_of),
        "unknown_queue": unknown_queue(memory, as_of=as_of),
        "wallet_radar": wallet_radar(memory, as_of=as_of),
        "creator_radar": creator_radar(memory, as_of=as_of),
        "pattern_radar": pattern_radar(memory, as_of=as_of),
        "observation_book": _observation_book(memory, as_of=as_of)[:40],
        "quality": _quality_desk(memory, as_of=as_of),
        "calibrated_probability": False,
    }


def _quality_desk(memory: IntelligenceMemory, *, as_of: Any = None) -> dict[str, Any]:
    from stinky_core.quality_state import evaluate_book, quality_dips, QUALITY_VERSION

    states = evaluate_book(memory, as_of=as_of)
    dips = quality_dips(states)
    counts: dict[str, int] = {}
    for s in states:
        st = str(s.get("state") or "UNKNOWN")
        counts[st] = counts.get(st, 0) + 1
    return {
        "version": QUALITY_VERSION,
        "states": states[:80],
        "dips": dips[:40],
        "counts": counts,
        "active_dips": len([d for d in dips if d.get("current_state") in ("WATCH", "DETERIORATING", "SEVERE_DETERIORATION", "FAILED")]),
        "calibrated_probability": False,
    }


def what_happened_next(memory: IntelligenceMemory, *, mint: str, t0: Any, as_of: Any = None) -> dict[str, Any]:
    return _what_happened_next(memory, mint=mint, t0=t0, as_of=as_of)


def observation_book(memory: IntelligenceMemory, *, as_of: Any = None) -> list[dict[str, Any]]:
    return _observation_book(memory, as_of=as_of)


def recipe_for(
    memory: IntelligenceMemory,
    fingerprint: str | None,
    *,
    as_of: Any = None,
    exclude_mint: str | None = None,
    current: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return runner_recipe(memory, fingerprint, as_of=as_of, exclude_mint=exclude_mint, current=current)
