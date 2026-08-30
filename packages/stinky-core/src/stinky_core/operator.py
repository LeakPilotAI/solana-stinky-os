"""Operator observability. Not a new brain. Not a buy.

Derives investigation lifecycle, watch status, provider/db health, traces,
and Discord policy-vs-delivery from stored records only.
Missing stays UNKNOWN. LIVE / FIXTURE / SIMULATION / MOCK never mix.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from stinky_core.memory import IntelligenceMemory, _parse_ts
from stinky_core.observation import OBSERVATION_SLICES_SEC, watch_should_resume
from stinky_core.quality_state import DIP_STATES, FAILED as QFAILED, UNKNOWN as QUNKNOWN

OPERATOR_VERSION = "operator-v1.1.0"
MAX_WATCH_SEC = 1800.0

EVIDENCE_LABELS = ("LIVE", "FIXTURE", "SIMULATION", "MOCK")

LIFECYCLE = (
    "DETECTED",
    "QUALIFIED",
    "INVESTIGATING",
    "WATCHING",
    "COMPLETED",
    "FAILED",
    "INTERRUPTED",
    "INCOMPLETE",
    "UNKNOWN",
)

DIP = DIP_STATES


def evidence_label(raw: Any) -> str:
    u = str(raw or "").strip().upper()
    if u in EVIDENCE_LABELS:
        return u
    return "UNKNOWN"


def live_gate1_status(*, count: int | None, explicit: str | None = None) -> str:
    """OBSERVED only from a counted LIVE Gate 1. Zero after a real probe is NOT OBSERVED."""
    exp = str(explicit or "").strip().upper()
    if exp in ("OBSERVED", "NOT OBSERVED") and count is None:
        return exp
    if count is None:
        return "UNKNOWN" if exp not in EVIDENCE_LABELS else "UNKNOWN"
    return "OBSERVED" if int(count) > 0 else "NOT OBSERVED"


def classify_delivery(*, attempted: bool | None, sent: int = 0, failed: int = 0) -> str:
    """Policy fired is not delivery. SENT only after a successful send."""
    if attempted is None:
        return "UNKNOWN"
    if not attempted:
        return "NOT ATTEMPTED"
    if int(sent) > 0:
        return "SENT"
    if int(failed) > 0:
        return "FAILED"
    return "UNKNOWN"


def _iso(v: Any) -> str | None:
    ts = _parse_ts(v)
    return ts.isoformat() if ts else (str(v).strip() or None if v else None)


def next_slice(elapsed_sec: float | None, slices: tuple[int, ...] = OBSERVATION_SLICES_SEC) -> dict[str, Any]:
    if elapsed_sec is None:
        return {"offset_sec": None, "label": "UNKNOWN", "reason": "elapsed_unknown"}
    try:
        e = float(elapsed_sec)
    except (TypeError, ValueError):
        return {"offset_sec": None, "label": "UNKNOWN", "reason": "elapsed_unknown"}
    for s in slices:
        if e < s:
            return {"offset_sec": s, "label": f"T+{s}"}
    return {"offset_sec": None, "label": "WINDOW_COMPLETE"}


def would_policy_fire(previous_state: str | None, current_state: str | None) -> bool:
    """Mirror Discord state-change policy without sending. Same-state is silent."""
    prev = (previous_state or "UNKNOWN").upper()
    cur = (current_state or "UNKNOWN").upper()
    if prev == cur or cur == "UNKNOWN":
        return False
    if cur in ("FAILED", "SEVERE_DETERIORATION", "DETERIORATING", "WATCH"):
        return True
    if prev in DIP and cur not in DIP:
        return True
    return False


def classify_lifecycle(
    *,
    investigation: dict[str, Any] | None,
    watch: dict[str, Any] | None,
    later_tick_count: int,
    elapsed_sec: float | None,
    quality_state: str | None,
    active: bool,
    max_watch_sec: float = MAX_WATCH_SEC,
    stop_reason: str | None = None,
    live: bool = False,
    last_observation_age_sec: float | None = None,
    stale_after_sec: float = 90.0,
) -> str:
    """Lifecycle from persisted evidence. Not inferred from price."""
    rec = investigation or {}
    wst = watch or {}
    has_rec = bool(str(rec.get("mint") or "").strip())
    has_watch = bool(str(wst.get("mint") or "").strip())
    stop = (stop_reason or wst.get("stop_reason") or "").upper()
    q = (quality_state or "").upper()

    if not has_rec and not has_watch:
        return "UNKNOWN"
    if not has_rec and has_watch:
        return "DETECTED"

    if elapsed_sec is not None:
        try:
            elapsed = float(elapsed_sec)
        except (TypeError, ValueError):
            elapsed = None
    else:
        elapsed = None

    window_open = elapsed is not None and 0 <= elapsed < float(max_watch_sec)
    window_closed = elapsed is not None and elapsed >= float(max_watch_sec)

    if stop in ("PROTOCOL_DISABLED", "INVALID_MINT", "PROTOCOL_UNKNOWN"):
        return "FAILED"
    if q == QFAILED:
        return "FAILED"
    stale = (
        last_observation_age_sec is not None
        and last_observation_age_sec > float(stale_after_sec)
        and window_open
        and not active
    )
    if live and window_open and has_rec and not active:
        return "INTERRUPTED"
    if stale:
        return "INTERRUPTED"
    if str(wst.get("status") or "").upper() == "INTERRUPTED" or wst.get("interrupted"):
        if window_open and not active:
            return "INTERRUPTED"
    if window_closed and later_tick_count < 2:
        return "INCOMPLETE"
    if window_closed:
        return "COMPLETED"
    if later_tick_count > 0 and (window_open or elapsed is None):
        return "WATCHING"
    if has_rec and later_tick_count <= 0:
        if elapsed is not None and elapsed == 0:
            return "QUALIFIED"
        return "INVESTIGATING"
    if has_rec:
        return "QUALIFIED"
    return "UNKNOWN"


def provider_health(probes: list[dict[str, Any]] | dict[str, Any] | None, *, name: str) -> dict[str, Any]:
    """Provider status from explicit probes only. No probe → UNKNOWN. Never a token dip."""
    empty = {
        "provider": name,
        "status": "UNKNOWN",
        "last_success_at": None,
        "last_failure_at": None,
        "latency_ms": None,
        "error": None,
        "source": None,
        "freshness": "UNKNOWN",
        "note": "No probe recorded. UNKNOWN is not UP.",
        "calibrated_probability": False,
    }
    rows: list[dict[str, Any]] = []
    if isinstance(probes, dict):
        rows = [probes] if (probes.get("provider") == name or not probes.get("provider")) else []
        if probes.get(name):
            rows = [probes[name]] if isinstance(probes[name], dict) else []
    elif isinstance(probes, list):
        rows = [p for p in probes if str(p.get("provider") or "") == name]
    if not rows:
        return empty
    last = rows[-1]
    status = str(last.get("status") or "UNKNOWN").upper()
    if status not in ("UP", "DEGRADED", "DOWN", "UNKNOWN"):
        status = "UNKNOWN"
    ok = last.get("ok")
    if status == "UNKNOWN" and ok is True:
        status = "UP"
    if status == "UNKNOWN" and ok is False:
        status = "DOWN"
    return {
        "provider": name,
        "status": status,
        "last_success_at": last.get("last_success_at") or (last.get("at") if ok else None),
        "last_failure_at": last.get("last_failure_at") or (last.get("at") if ok is False else None),
        "latency_ms": last.get("latency_ms"),
        "http_status": last.get("http_status"),
        "error": last.get("error"),
        "source": last.get("source") or name,
        "freshness": last.get("at") or "UNKNOWN",
        "note": last.get("note") or "Provider failure is data-quality, not token deterioration.",
        "calibrated_probability": False,
    }


def database_health(
    *,
    connected: bool | None,
    last_write_at: Any = None,
    last_read_at: Any = None,
    error: str | None = None,
    pending: int | None = None,
    investigations: int = 0,
    watches: int = 0,
) -> dict[str, Any]:
    if connected is True:
        status = "CONNECTED"
    elif connected is False:
        status = "DOWN"
    else:
        status = "UNKNOWN"
    if connected is True and error:
        status = "DEGRADED"
    return {
        "status": status,
        "last_successful_write": _iso(last_write_at) or ("UNKNOWN" if last_write_at is None else str(last_write_at)),
        "last_successful_read": _iso(last_read_at) or ("UNKNOWN" if last_read_at is None else str(last_read_at)),
        "pending_persistence": pending,
        "active_investigation_count": investigations,
        "active_watch_count": watches,
        "error": error,
        "note": "UNKNOWN if Postgres was not probed. Never claim healthy without a successful read/write.",
        "calibrated_probability": False,
    }


def discord_status(*, policy_fired: bool | None, delivery: str | None, error: str | None = None) -> dict[str, Any]:
    pol = "UNKNOWN" if policy_fired is None else ("FIRED" if policy_fired else "NOT FIRED")
    deliv = str(delivery or "UNKNOWN").upper()
    if deliv not in ("SENT", "FAILED", "NOT ATTEMPTED", "UNKNOWN"):
        deliv = "UNKNOWN"
    return {
        "policy": pol,
        "delivery": deliv,
        "error": error,
        "note": "Policy fired is not delivery. SENT only after a successful Discord API call.",
        "calibrated_probability": False,
        "not_a_buy": True,
    }


def watch_view(
    *,
    mint: str,
    watch: dict[str, Any] | None,
    t0: Any,
    now: Any,
    observation_count: int,
    provider: dict[str, Any] | None,
    persistence_status: str | None,
    active: bool,
    max_watch_sec: float = MAX_WATCH_SEC,
    interval_sec: float = 20.0,
) -> dict[str, Any]:
    start = _parse_ts((watch or {}).get("started_at") or t0)
    now_ts = _parse_ts(now) or datetime.now(timezone.utc)
    elapsed = (now_ts - start).total_seconds() if start else None
    last_obs = _parse_ts((watch or {}).get("last_observation_at"))
    nxt = next_slice(elapsed)
    next_poll = None
    if last_obs is not None:
        next_poll = last_obs.timestamp() + float(interval_sec)
        next_poll = datetime.fromtimestamp(next_poll, tz=timezone.utc).isoformat()
    resumed = bool((watch or {}).get("resumed"))
    return {
        "investigation_id": (watch or {}).get("investigation_id") or mint,
        "mint": mint,
        "started_at": start.isoformat() if start else None,
        "elapsed_sec": round(elapsed, 1) if elapsed is not None else None,
        "next_scheduled_observation": nxt,
        "next_poll_at": next_poll,
        "last_successful_observation": last_obs.isoformat() if last_obs else None,
        "observation_count": observation_count,
        "provider_status": (provider or {}).get("status") or "UNKNOWN",
        "persistence_status": persistence_status or (watch or {}).get("persistence_status") or "UNKNOWN",
        "active": active,
        "resumed": resumed,
        "resume_note": "Watch resumed after process restart." if resumed else None,
        "window_open": watch_should_resume(elapsed_sec=elapsed or -1, max_watch_sec=max_watch_sec) if elapsed is not None else False,
        "calibrated_probability": False,
    }


def quality_dip_trace(transitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve previous → new with evidence. Price-down alone is not listed unless in why."""
    out: list[dict[str, Any]] = []
    for t in transitions:
        cur = str(t.get("state") or QUNKNOWN)
        prev = str(t.get("previous_state") or QUNKNOWN)
        if cur not in DIP and not (prev in DIP and cur not in DIP and cur != QUNKNOWN):
            continue
        why = t.get("why") or []
        first = why[0] if why else {}
        if not isinstance(first, dict):
            first = {"explanation": str(first)}
        out.append(
            {
                "mint": t.get("mint"),
                "previous_state": prev,
                "new_state": cur,
                "timestamp": t.get("as_of"),
                "severity": t.get("severity"),
                "evidence": why,
                "metric": first.get("metric"),
                "old_value": first.get("previous_value"),
                "new_value": first.get("current_value"),
                "source": first.get("source") or "observed_market_tick",
                "data_quality": t.get("evidence_quality") or "UNKNOWN",
                "calibrated_probability": False,
                "note": "Setup deterioration, not a price-down buy.",
            }
        )
    return out


def build_trace(events: list[dict[str, Any]], *, mint: str | None = None) -> list[dict[str, Any]]:
    rows = [dict(e) for e in events if not mint or e.get("mint") == mint]
    rows.sort(key=lambda e: str(e.get("at") or ""))
    out: list[dict[str, Any]] = []
    for e in rows:
        out.append(
            {
                "at": e.get("at"),
                "kind": e.get("kind"),
                "message": e.get("message"),
                "mint": e.get("mint"),
                "evidence_label": evidence_label(e.get("evidence_label")),
                "delivery": e.get("delivery"),
                "policy": e.get("policy"),
                "state": e.get("state"),
                "previous_state": e.get("previous_state"),
            }
        )
    return out


def last_observation_view(memory: IntelligenceMemory) -> dict[str, Any]:
    """Most recent stored tick or operator event. Empty is UNKNOWN."""
    events = list(getattr(memory, "operator_events", []) or [])
    ticks = list(getattr(memory, "market_ticks", []) or [])
    last_tick = max(ticks, key=lambda t: t.observed_at) if ticks else None
    last_evt = events[-1] if events else None
    tick_at = last_tick.observed_at if last_tick else None
    evt_at = _parse_ts((last_evt or {}).get("at"))
    use_tick = tick_at is not None and (evt_at is None or tick_at >= evt_at)
    if use_tick and last_tick is not None:
        return {
            "at": last_tick.observed_at.isoformat(),
            "mint": last_tick.mint,
            "kind": "market_tick",
            "volume_m5_usd": last_tick.volume_m5_usd,
            "evidence_label": evidence_label(getattr(last_tick, "evidence_label", None)),
        }
    if last_evt:
        return {
            "at": last_evt.get("at"),
            "mint": last_evt.get("mint"),
            "kind": last_evt.get("kind") or "UNKNOWN",
            "message": last_evt.get("message"),
            "evidence_label": evidence_label(last_evt.get("evidence_label")),
        }
    return {
        "at": None,
        "mint": None,
        "kind": "UNKNOWN",
        "evidence_label": "UNKNOWN",
        "note": "No observation stored.",
    }


def count_live_gate1(memory: IntelligenceMemory) -> int:
    """LIVE Gate 1 prints only. Unlabeled rows are not counted as LIVE."""
    mints: set[str] = set()
    for rec in list(getattr(memory, "investigations", []) or []):
        mint = str(rec.get("mint") or "").strip()
        if mint and evidence_label(rec.get("evidence_label")) == "LIVE":
            mints.add(mint)
    for e in list(getattr(memory, "operator_events", []) or []):
        mint = str(e.get("mint") or "").strip()
        if mint and evidence_label(e.get("evidence_label")) == "LIVE" and str(e.get("kind") or "") == "gate1":
            mints.add(mint)
    return len(mints)


def investigation_card(
    memory: IntelligenceMemory,
    *,
    mint: str,
    now: Any = None,
    active: bool = False,
    live: bool = False,
    max_watch_sec: float = MAX_WATCH_SEC,
    evidence_label_default: str = "UNKNOWN",
) -> dict[str, Any]:
    now_ts = _parse_ts(now) or datetime.now(timezone.utc)
    rec = next((r for r in memory.investigations if r.get("mint") == mint), None)
    watch = next((w for w in reversed(getattr(memory, "watch_states", []) or []) if w.get("mint") == mint), None)
    ticks = sorted((t for t in memory.market_ticks if t.mint == mint), key=lambda x: x.observed_at)
    t0 = _parse_ts((rec or {}).get("gate1_at") or (rec or {}).get("decision_timestamp") or (watch or {}).get("started_at"))
    later = [t for t in ticks if t0 and t.observed_at > t0]
    elapsed = (now_ts - t0).total_seconds() if t0 else None
    qrows = [q for q in (getattr(memory, "quality_states", []) or []) if q.get("mint") == mint]
    q = qrows[-1] if qrows else None
    latest = ticks[-1] if ticks else None
    last_obs = _parse_ts((watch or {}).get("last_observation_at")) or (latest.observed_at if latest else None)
    age = (now_ts - last_obs).total_seconds() if last_obs else None
    life = classify_lifecycle(
        investigation=rec,
        watch=watch,
        later_tick_count=len(later),
        elapsed_sec=elapsed,
        quality_state=(q or {}).get("state"),
        active=active,
        max_watch_sec=max_watch_sec,
        stop_reason=(watch or {}).get("stop_reason"),
        live=live,
        last_observation_age_sec=age,
    )
    probes = [p for p in (getattr(memory, "provider_probes", []) or []) if p.get("provider") == "dexscreener"]
    prov = provider_health(probes, name="dexscreener")
    label = evidence_label((rec or {}).get("evidence_label") or (watch or {}).get("evidence_label") or evidence_label_default)
    unknown: list[str] = []
    if not rec:
        unknown.append("investigation")
    if not t0:
        unknown.append("gate_time")
    if latest is None:
        unknown.append("current_volume")
    if not q:
        unknown.append("quality_state")
    return {
        "version": OPERATOR_VERSION,
        "mint": mint,
        "symbol": (rec or {}).get("symbol") or (watch or {}).get("symbol"),
        "pool": (rec or {}).get("pair_identifier") or (watch or {}).get("pool"),
        "protocol": (rec or {}).get("protocol"),
        "lifecycle": life,
        "gate_time": t0.isoformat() if t0 else None,
        "gate_volume": (rec or {}).get("volume_5m_at_gate"),
        "current_volume": latest.volume_m5_usd if latest else None,
        "current_liquidity": latest.liquidity_usd if latest else None,
        "current_quality": (q or {}).get("state") or QUNKNOWN,
        "previous_quality": (q or {}).get("previous_state"),
        "quality_why": (q or {}).get("why") or [],
        "quality_evidence": (q or {}).get("evidence_quality") or "UNKNOWN",
        "watch_age_sec": round(elapsed, 1) if elapsed is not None else None,
        "next_tick": next_slice(elapsed),
        "observation_count": len(ticks),
        "later_tick_count": len(later),
        "data_quality": (q or {}).get("evidence_quality") or ("UNKNOWN" if not ticks else "LIMITED"),
        "provider": prov,
        "watch": watch_view(
            mint=mint,
            watch=watch,
            t0=t0,
            now=now_ts,
            observation_count=len(ticks),
            provider=prov,
            persistence_status=(watch or {}).get("persistence_status"),
            active=active,
            max_watch_sec=max_watch_sec,
        ),
        "unknown": unknown,
        "evidence_label": label,
        "calibrated_probability": False,
        "note": "Values are stored observations. UNKNOWN means we do not have the field.",
    }


def export_investigation(
    memory: IntelligenceMemory,
    *,
    mint: str,
    now: Any = None,
    evidence_label_default: str = "UNKNOWN",
) -> dict[str, Any]:
    """Operator-readable summary from persisted data only."""
    from stinky_core.observation import slice_analogues, what_happened_next
    from stinky_core.recipes import runner_recipe

    card = investigation_card(memory, mint=mint, now=now, evidence_label_default=evidence_label_default)
    rec = next((r for r in memory.investigations if r.get("mint") == mint), None)
    t0 = (rec or {}).get("gate1_at") or (rec or {}).get("decision_timestamp")
    happened = what_happened_next(memory, mint=mint, t0=t0, as_of=now) if t0 else {"outcome": {"label": "UNKNOWN"}, "note": "no t0"}
    ana = (
        slice_analogues(memory, mint=mint, offset_sec=15, t0=t0, as_of=now)
        if t0
        else {"analogue_count": 0, "sample_sufficient": False, "calibrated_probability": False}
    )
    fp = (rec or {}).get("fingerprint")
    recipe = runner_recipe(memory, fp, as_of=now or t0, exclude_mint=mint) if fp else {
        "analogue_count": 0,
        "sample_sufficient": False,
        "calibrated_probability": False,
        "note": "No fingerprint on investigation. Recipe UNKNOWN.",
    }
    qrows = [q for q in (getattr(memory, "quality_states", []) or []) if q.get("mint") == mint]
    deliveries = [d for d in (getattr(memory, "discord_deliveries", []) or []) if d.get("mint") == mint]
    events = build_trace(getattr(memory, "operator_events", []) or [], mint=mint)
    last_del = deliveries[-1] if deliveries else None
    last_q = qrows[-1] if qrows else None
    policy = would_policy_fire((last_q or {}).get("previous_state"), (last_q or {}).get("state")) if last_q else False
    unknown = list(card.get("unknown") or [])
    if (ana.get("analogue_count") or 0) < 5:
        unknown.append("analogues_insufficient")
    if not fp:
        unknown.append("fingerprint")
    return {
        "version": OPERATOR_VERSION,
        "evidence_label": card["evidence_label"],
        "token": card.get("symbol"),
        "mint": mint,
        "pool": card.get("pool"),
        "migration": (rec or {}).get("protocol") or "UNKNOWN",
        "gate": {"at": card.get("gate_time"), "volume_5m": card.get("gate_volume")},
        "lifecycle": card["lifecycle"],
        "observations": {
            "count": card["observation_count"],
            "later": card["later_tick_count"],
            "next": card["next_tick"],
        },
        "quality_timeline": [
            {
                "at": q.get("as_of"),
                "state": q.get("state"),
                "previous": q.get("previous_state"),
                "why": q.get("why"),
                "evidence_quality": q.get("evidence_quality"),
            }
            for q in qrows
        ],
        "quality_dips": quality_dip_trace(qrows),
        "outcome": happened.get("outcome") if isinstance(happened.get("outcome"), dict) else {"label": happened.get("outcome") or "UNKNOWN"},
        "analogues": {
            "analogue_count": ana.get("analogue_count"),
            "sample_sufficient": ana.get("sample_sufficient"),
            "note": ana.get("note"),
            "calibrated_probability": False,
        },
        "recipes": {
            "analogue_count": recipe.get("analogue_count"),
            "sample_sufficient": recipe.get("sample_sufficient"),
            "note": recipe.get("note"),
            "calibrated_probability": False,
        },
        "entity_intelligence": {
            "creator": (rec or {}).get("creator") or "UNKNOWN",
            "note": "Live DexScreener does not invent buyers. UNKNOWN until captured.",
        },
        "data_quality": card.get("data_quality"),
        "unknown_fields": unknown,
        "discord_events": [
            {
                "at": d.get("at"),
                "policy": d.get("policy"),
                "delivery": d.get("delivery"),
                "category": d.get("category"),
                "error": d.get("error"),
            }
            for d in deliveries
        ],
        "discord": discord_status(
            policy_fired=policy if last_q else None,
            delivery=(last_del or {}).get("delivery"),
            error=(last_del or {}).get("error"),
        ),
        "trace": events,
        "what_happened": happened,
        "calibrated_probability": False,
        "note": "Generated from persisted records. Empty layers stay UNKNOWN.",
    }


def operator_desk(
    memory: IntelligenceMemory,
    *,
    now: Any = None,
    db: dict[str, Any] | None = None,
    active_mints: list[str] | None = None,
    evidence_label_default: str = "UNKNOWN",
    live_gate1_count: int | None = None,
    live_gate1_label: str = "UNKNOWN",
) -> dict[str, Any]:
    now_ts = _parse_ts(now) or datetime.now(timezone.utc)
    active = set(active_mints or [])
    mints: list[str] = []
    seen: set[str] = set()
    for rec in list(memory.investigations) + list(getattr(memory, "watch_states", []) or []):
        m = str(rec.get("mint") or "").strip()
        if m and m not in seen:
            seen.add(m)
            mints.append(m)
    cards = [
        investigation_card(
            memory,
            mint=m,
            now=now_ts,
            active=m in active,
            live=False,
            evidence_label_default=evidence_label_default,
        )
        for m in mints
    ]
    watching = [c for c in cards if c["lifecycle"] in ("WATCHING", "INVESTIGATING", "QUALIFIED", "DETECTED")]
    probes = getattr(memory, "provider_probes", []) or []
    providers = {
        "dexscreener": provider_health(probes, name="dexscreener"),
        "solana_ws": provider_health(probes, name="solana_ws"),
        "postgres": provider_health(probes, name="postgres"),
        "discord": provider_health(probes, name="discord"),
    }
    last_write = None
    for t in memory.market_ticks:
        if last_write is None or t.observed_at > last_write:
            last_write = t.observed_at
    db_row = db or {}
    database = database_health(
        connected=db_row.get("connected"),
        last_write_at=db_row.get("last_write_at") or last_write,
        last_read_at=db_row.get("last_read_at"),
        error=db_row.get("error"),
        pending=db_row.get("pending"),
        investigations=len(memory.investigations),
        watches=len([c for c in cards if c["watch"]["window_open"]]),
    )
    deliveries = list(getattr(memory, "discord_deliveries", []) or [])
    last_del = deliveries[-1] if deliveries else None
    counted = count_live_gate1(memory) if live_gate1_count is None else int(live_gate1_count)
    if live_gate1_count is not None:
        gate_label = live_gate1_status(count=live_gate1_count)
    elif live_gate1_label in ("OBSERVED", "NOT OBSERVED"):
        gate_label = live_gate1_label
    elif db_row.get("connected") is True:
        gate_label = live_gate1_status(count=counted)
    else:
        gate_label = "OBSERVED" if counted > 0 else "UNKNOWN"

    qrows = list(getattr(memory, "quality_states", []) or [])
    latest_q = qrows[-1] if qrows else None
    last_obs = last_observation_view(memory)
    open_watches = [c["watch"] for c in cards if c["watch"]["window_open"] or c["watch"]["active"]]
    if open_watches:
        nxt = open_watches[0].get("next_scheduled_observation") or next_slice(open_watches[0].get("elapsed_sec"))
    else:
        nxt = {"offset_sec": None, "label": "NONE", "reason": "no_active_watch"}

    return {
        "version": OPERATOR_VERSION,
        "as_of": now_ts.isoformat(),
        "system_status": "OBSERVING" if watching else "IDLE",
        "live_data_status": providers["dexscreener"]["status"],
        "migration_watch_status": providers["solana_ws"]["status"],
        "gate_status": {
            "threshold_usd": 150_000,
            "clamp_usd": 200_000,
            "live_gate1_count": counted if live_gate1_count is not None or db_row.get("connected") is True else None,
            "live_gate1": gate_label,
            "note": "Gate 1 is $150k 5m. Do not lower. NOT OBSERVED is not a failure.",
        },
        "last_observation": last_obs,
        "next_observation": nxt,
        "quality_state": {
            "current": (latest_q or {}).get("state") or "UNKNOWN",
            "previous": (latest_q or {}).get("previous_state"),
            "at": (latest_q or {}).get("as_of"),
            "mint": (latest_q or {}).get("mint"),
            "dips": quality_dip_trace(qrows),
        },
        "database": database,
        "providers": providers,
        "discord": discord_status(
            policy_fired=None if not last_del else str(last_del.get("policy") or "").upper() == "FIRED",
            delivery=(last_del or {}).get("delivery"),
            error=(last_del or {}).get("error"),
        ),
        "active_investigations": [c for c in cards if c["lifecycle"] in ("QUALIFIED", "INVESTIGATING", "WATCHING")],
        "active_watches": open_watches,
        "investigations": cards,
        "counts": {
            "investigations": len(memory.investigations),
            "watches_open": len([c for c in cards if c["watch"]["window_open"]]),
            "quality_transitions": len(qrows),
            "operator_events": len(getattr(memory, "operator_events", []) or []),
        },
        "calibrated_probability": False,
        "note": "Operator desk. Empty is empty. Provider DOWN is not a quality dip.",
    }
