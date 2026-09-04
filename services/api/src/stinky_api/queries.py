"""Read-only SQL against Stinky OS Postgres tables.

No business logic invention — only surfaces derived state that already exists.
"""

from __future__ import annotations

from typing import Any
import httpx

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from stinky_core.admission import FilterConfig, evaluate_market
    from stinky_core.fees import coerce_fees_verified, extract_explicit_api_fees
except ImportError:  # pragma: no cover
    evaluate_market = None  # type: ignore[assignment]
    FilterConfig = None  # type: ignore[assignment]
    coerce_fees_verified = None  # type: ignore[assignment]
    extract_explicit_api_fees = None  # type: ignore[assignment]


def apply_canonical_gate(row: dict[str, Any], *, min_fees_sol: float = 1.0) -> dict[str, Any]:
    """Stamp eligibility from the single canonical engine. Fail closed.

    A bare fee number is NEVER treated as verified.
    Unknown fees do NOT reject Gate 1.
    """
    out = dict(row)
    if evaluate_market is None:
        out["eligible"] = False
        out["rejection_reason"] = "INVALID_MARKET_DATA"
        out["reason_codes"] = ["INVALID_MARKET_DATA"]
        return out
    fees = out.get("global_fees_sol")
    if fees is None:
        fees = out.get("fees_sol")
    if fees is None:
        fees = out.get("global_fees_paid_sol")
    verified = None
    if coerce_fees_verified is not None:
        verified = coerce_fees_verified(out.get("global_fees_verified"))
        if verified is None:
            verified = coerce_fees_verified(out.get("fees_verified"))
    else:
        raw = out.get("global_fees_verified")
        verified = True if raw is True else (False if raw is False else None)
    decision = evaluate_market(
        {
            "mint": out.get("mint"),
            "protocol": out.get("protocol") or out.get("dex_id") or "pumpfun",
            "dex_id": out.get("dex_id"),
            "global_fees_sol": fees if verified is True else None,
            "global_fees_verified": verified,
            "global_fees_source": out.get("global_fees_source") or out.get("fees_source"),
            "liquidity_usd": out.get("liquidity_usd"),
            "volume_usd": out.get("volume_m5_usd") or out.get("volume_usd"),
            "market_cap_usd": out.get("market_cap_usd") or out.get("fdv_usd"),
            "twitter": out.get("twitter"),
            "website": out.get("website"),
            "telegram": out.get("telegram"),
            "tiktok": out.get("tiktok"),
            "migrated": True,
            "tab": "migrated",
        },
        config=FilterConfig(min_global_fees_sol=float(min_fees_sol)),
    )
    out["eligible"] = decision.eligible
    out["rejection_reason"] = decision.rejection_reason
    out["reason_codes"] = decision.reason_codes
    out["failed_filters"] = decision.failed_filters
    out["passed_filters"] = decision.passed_filters
    out["filter_version"] = decision.filter_version
    out["normalized_metrics"] = decision.normalized_metrics
    out["fee_signal"] = (decision.metrics or {}).get("fee_signal")
    out["global_fees_verified"] = verified is True
    if verified is True and fees is not None:
        out["fees_sol"] = fees
        out["global_fees_sol"] = fees
    else:
        out["fees_sol"] = fees if verified is True else None
        out["global_fees_sol"] = fees if verified is True else None
    return out


LEADERBOARD_DENYLIST = (
    "11111111111111111111111111111111",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
    "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
    "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg",
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
)


def _ser(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif hasattr(v, "__float__") and type(v).__name__ in ("Decimal",):
            out[k] = float(v)
        else:
            out[k] = v
    return out


async def counts(session: AsyncSession) -> dict[str, int]:
    q = text(
        """
        SELECT
          (SELECT COUNT(*) FROM events WHERE event_type = 'token.migrated')::int AS migrations,
          (SELECT COUNT(*) FROM events WHERE event_type = 'token.launch')::int AS launches,
          (SELECT COUNT(*) FROM events WHERE event_type = 'alert.candidate')::int AS alerts,
          (SELECT COUNT(*) FROM migration_tracks)::int AS tracks,
          (SELECT COUNT(*) FROM migration_buyers)::int AS buyers,
          (SELECT COUNT(*) FROM entities)::int AS entities,
          (SELECT COUNT(*) FROM wallet_performance)::int AS wallets_perf
        """
    )
    try:
        row = (await session.execute(q)).mappings().first()
        return dict(row) if row else {}
    except Exception:
        # Partial schema during early boot
        return {
            "migrations": 0,
            "launches": 0,
            "alerts": 0,
            "tracks": 0,
            "buyers": 0,
            "entities": 0,
            "wallets_perf": 0,
        }


async def _fetch_pump_fees_sol(mint: str) -> tuple[float | None, bool, str | None]:
    """Explicit pump.fun fee fields only. creator_fees_* is not global fees.

    Returns (value, verified, source_key). List endpoints do NOT run on-chain
    resolution (too slow); missing explicit field → (None, False, None).
    """
    if not mint or extract_explicit_api_fees is None:
        return None, False, None
    urls = [
        f"https://frontend-api-v3.pump.fun/coins/{mint}",
        f"https://frontend-api.pump.fun/coins/{mint}",
    ]
    async with httpx.AsyncClient(timeout=6.0) as client:
        for url in urls:
            try:
                resp = await client.get(url, headers={"Accept": "application/json"})
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if not isinstance(data, dict):
                    continue
                val, key, _raw = extract_explicit_api_fees(data)
                if val is not None and key is not None:
                    return val, True, f"pump.fun/{key}"
            except Exception:
                continue
    return None, False, None


async def recent_migrations(
    session: AsyncSession,
    limit: int = 25,
    *,
    min_fees_sol: float = 0.0,
    min_volume_m5_usd: float = 33_000.0,
    pump_only: bool = True,
    enrich_fees: bool = False,
) -> list[dict]:
    """Live runners from migration_tracks + latest snapshots (fast, realtime-friendly).

    Fee enrichment is optional and off by default so the UI never hangs.
    Pump filter keeps mint suffix ...pump when pump_only=True.
    """
    pump_clause = "WHERE lower(mt.mint) LIKE '%pump'" if pump_only else ""
    rows = (
        await session.execute(
            text(
                f"""
                SELECT
                  mt.mint,
                  mt.pool,
                  mt.creator,
                  mt.migration_at,
                  mt.status,
                  mt.buyers_captured,
                  mt.trades_observed,
                  COALESCE(mt.buyers_captured, 0)::int AS meaningful_buyers,
                  ms.volume_m5_usd,
                  ms.liquidity_usd,
                  ms.price_usd,
                  ms.dex_id,
                  ms.captured_at AS snapshot_at
                FROM migration_tracks mt
                LEFT JOIN LATERAL (
                  SELECT volume_m5_usd, liquidity_usd, price_usd, dex_id, captured_at
                  FROM market_snapshots
                  WHERE mint = mt.mint
                  ORDER BY captured_at DESC
                  LIMIT 1
                ) ms ON TRUE
                {pump_clause}
                ORDER BY mt.migration_at DESC NULLS LAST
                LIMIT :lim
                """
            ),
            {"lim": max(limit * 2, 40)},
        )
    ).mappings().all()

    denied = {
        "meteora", "raydium", "orca", "phoenix", "lifinity",
        "saber", "aldrin", "fluxbeam",
    }
    allowed_hints = ("pump", "pumpswap", "pumpfun")

    out: list[dict] = []
    for r in rows:
        d = _ser(dict(r))
        mint = str(d.get("mint") or "")
        if pump_only and mint and not mint.lower().endswith("pump"):
            continue
        dex = str(d.get("dex_id") or "").lower()
        if dex:
            if any(x in dex for x in denied):
                continue
            # if dex is known non-pump family, skip; unknown/empty allowed
            if not any(a in dex for a in allowed_hints) and dex not in ("", "unknown"):
                # still allow if empty path above; only filter clear non-pump
                if any(x in dex for x in ("raydium", "meteora", "orca")):
                    continue
        out.append(d)
        if len(out) >= limit:
            break

    # Fee enrich is optional evidence. Gate 1 is volume, not fees.
    gated_out: list[dict] = []
    for d in out:
        if min_volume_m5_usd and d.get("volume_m5_usd") is not None:
            try:
                if float(d["volume_m5_usd"]) + 1e-9 < float(min_volume_m5_usd):
                    continue
            except (TypeError, ValueError):
                continue
        gated = apply_canonical_gate(d, min_fees_sol=min_fees_sol or 1.0)
        if not gated.get("eligible"):
            continue
        gated_out.append(gated)
        if len(gated_out) >= limit:
            break

    if enrich_fees and gated_out:
        import asyncio

        async def _one(d: dict) -> dict:
            fees = d.get("fees_sol")
            verified = coerce_fees_verified(d.get("global_fees_verified")) if coerce_fees_verified else None
            try:
                fees_f = float(fees) if fees is not None else None
            except (TypeError, ValueError):
                fees_f = None
            if verified is not True:
                try:
                    fees_f, verified_flag, source = await asyncio.wait_for(
                        _fetch_pump_fees_sol(str(d.get("mint") or "")),
                        timeout=2.5,
                    )
                    verified = True if verified_flag else None
                    if source:
                        d["global_fees_source"] = source
                except Exception:
                    fees_f = None
                    verified = None
            d["fees_sol"] = fees_f if verified is True else None
            d["global_fees_paid_sol"] = d["fees_sol"]
            d["global_fees_sol"] = d["fees_sol"]
            d["global_fees_verified"] = verified is True
            return d

        enriched = await asyncio.gather(*[_one(dict(d)) for d in gated_out[:limit]])
        return [apply_canonical_gate(d, min_fees_sol=min_fees_sol or 1.0) for d in enriched][:limit]

    return gated_out[:limit]


async def recent_alerts(session: AsyncSession, limit: int = 20) -> list[dict]:
    q = text(
        """
        SELECT
          event_id::text,
          occurred_at,
          payload->>'mint' AS mint,
          payload->>'name' AS name,
          payload->>'symbol' AS symbol,
          payload->>'creator' AS creator,
          payload->>'pool' AS pool,
          (payload->>'volume_m5_usd')::float AS volume_m5_usd,
          (payload->>'liquidity_usd')::float AS liquidity_usd,
          (payload->>'stinky_score')::float AS stinky_score,
          (payload->>'confidence')::float AS confidence,
          (payload->>'meaningful_buyer_count')::int AS meaningful_buyer_count,
          (payload->>'early_buyer_count')::int AS early_buyer_count,
          (payload->>'smart_wallet_count')::int AS smart_wallet_count,
          payload->>'score_model' AS score_model,
          payload->'score_explanation' AS score_explanation
        FROM events
        WHERE event_type = 'alert.candidate'
        ORDER BY occurred_at DESC
        LIMIT :lim
        """
    )
    try:
        rows = (await session.execute(q, {"lim": limit})).mappings().all()
        return [_ser(dict(r)) for r in rows]
    except Exception:
        return []


async def top_entities(session: AsyncSession, limit: int = 15) -> list[dict]:
    q = text(
        """
        SELECT entity_id::text, entity_type, display_label, primary_wallet,
               wallet_count, launch_count, early_buy_count, confidence,
               created_at, updated_at
        FROM entities
        ORDER BY launch_count DESC NULLS LAST, confidence DESC
        LIMIT :lim
        """
    )
    try:
        rows = (await session.execute(q, {"lim": limit})).mappings().all()
        return [_ser(dict(r)) for r in rows]
    except Exception:
        return []


async def top_wallets(session: AsyncSession, limit: int = 15) -> list[dict]:
    """Leaderboard from wallet_performance + measured wallet_early_success when present."""
    q = text(
        """
        SELECT wp.wallet, wp.total_trades, wp.total_buys, wp.total_sells,
               wp.tokens_purchased, wp.early_buy_count, wp.qualifying_trades,
               wp.wins, wp.losses, wp.loss_rate, wp.hit_rate,
               wp.avg_return_pct, wp.median_return_pct, wp.max_return_pct,
               wp.avg_holding_seconds, wp.realized_pnl_usd, wp.realized_pnl_sol,
               wp.updated_at,
               wes.success_rate AS early_success_rate,
               wes.sample_size AS early_success_sample,
               wes.early_on_mega,
               wes.early_on_runner,
               wes.early_on_mid,
               wes.early_on_fade,
               wes.early_entries AS early_success_entries
        FROM wallet_performance wp
        LEFT JOIN wallet_early_success wes ON wes.wallet = wp.wallet
        WHERE wp.early_buy_count > 0 OR wp.total_buys > 0
        ORDER BY
          COALESCE(wes.success_rate, 0) DESC NULLS LAST,
          COALESCE(wes.early_on_runner, 0) + COALESCE(wes.early_on_mega, 0) DESC,
          wp.early_buy_count DESC NULLS LAST,
          wp.hit_rate DESC NULLS LAST,
          wp.avg_return_pct DESC NULLS LAST
        LIMIT :lim
        """
    )
    q_fallback = text(
        """
        SELECT wallet, total_trades, total_buys, total_sells,
               tokens_purchased, early_buy_count, qualifying_trades,
               wins, losses, loss_rate, hit_rate,
               avg_return_pct, median_return_pct, max_return_pct,
               avg_holding_seconds, realized_pnl_usd, realized_pnl_sol,
               updated_at
        FROM wallet_performance
        WHERE early_buy_count > 0 OR total_buys > 0
        ORDER BY early_buy_count DESC NULLS LAST,
                 hit_rate DESC NULLS LAST,
                 avg_return_pct DESC NULLS LAST
        LIMIT :lim
        """
    )
    try:
        try:
            rows = (await session.execute(q, {"lim": max(limit * 3, 40)})).mappings().all()
        except Exception:
            await session.rollback()
            rows = (await session.execute(q_fallback, {"lim": max(limit * 3, 40)})).mappings().all()
        blocked = set(LEADERBOARD_DENYLIST)
        out = []
        for r in rows:
            d = _ser(dict(r))
            w = d.get("wallet") or ""
            if w in blocked or len(w) < 32:
                continue
            out.append(d)
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


async def recent_launches(session: AsyncSession, limit: int = 15) -> list[dict]:
    q = text(
        """
        SELECT
          event_id::text,
          occurred_at,
          payload->>'mint' AS mint,
          payload->>'name' AS name,
          payload->>'symbol' AS symbol,
          payload->>'deployer' AS deployer,
          (payload->>'stinky_score')::float AS stinky_score,
          (payload->>'confidence')::float AS confidence
        FROM events
        WHERE event_type = 'token.launch'
        ORDER BY occurred_at DESC
        LIMIT :lim
        """
    )
    try:
        rows = (await session.execute(q, {"lim": limit})).mappings().all()
        return [_ser(dict(r)) for r in rows]
    except Exception:
        return []


async def search_all(session: AsyncSession, qstr: str, limit: int = 10) -> dict[str, list]:
    qstr = (qstr or "").strip()
    if len(qstr) < 2:
        return {"tokens": [], "wallets": [], "entities": [], "alerts": []}

    like = f"%{qstr}%"
    # Exact / prefix helpers for base58 CAs (case-sensitive on chain, store as-is)
    prefix = f"{qstr}%"
    tokens: list[dict] = []
    wallets: list[dict] = []
    entities: list[dict] = []
    alerts: list[dict] = []
    seen_mints: set[str] = set()

    def _add_token(d: dict) -> None:
        m = d.get("mint")
        if not m or m in seen_mints:
            return
        seen_mints.add(m)
        tokens.append(_ser(d))

    # 1) migration_tracks (strongest signal for post-bond mints)
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT mint, creator, migration_at, status,
                           buyers_captured, trades_observed
                    FROM migration_tracks
                    WHERE mint ILIKE :like OR mint LIKE :prefix OR mint = :exact
                    ORDER BY migration_at DESC NULLS LAST
                    LIMIT :lim
                    """
                ),
                {"like": like, "prefix": prefix, "exact": qstr, "lim": limit},
            )
        ).mappings().all()
        for r in rows:
            d = dict(r)
            d.setdefault("name", None)
            d.setdefault("symbol", None)
            _add_token(d)
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass

    # 2) events (launch / migrated / alert)
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT ON (payload->>'mint')
                      payload->>'mint' AS mint,
                      payload->>'name' AS name,
                      payload->>'symbol' AS symbol,
                      occurred_at
                    FROM events
                    WHERE event_type IN ('token.launch', 'token.migrated', 'alert.candidate')
                      AND (
                        payload->>'mint' ILIKE :like
                        OR payload->>'mint' LIKE :prefix
                        OR payload->>'mint' = :exact
                        OR payload->>'name' ILIKE :like
                        OR payload->>'symbol' ILIKE :like
                      )
                    ORDER BY payload->>'mint', occurred_at DESC
                    LIMIT :lim
                    """
                ),
                {"like": like, "prefix": prefix, "exact": qstr, "lim": limit},
            )
        ).mappings().all()
        for r in rows:
            _add_token(dict(r))
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass

    # 3) If query looks like a mint/wallet and no token hit, still surface synthetic token row
    looks_addr = 32 <= len(qstr) <= 50 and all(
        c.isalnum() or c in "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        for c in qstr
    )
    if looks_addr and qstr.endswith("pump") and qstr not in seen_mints:
        _add_token({"mint": qstr, "name": None, "symbol": None, "source": "direct"})
    elif looks_addr and not tokens and qstr not in seen_mints:
        # could be wallet; still allow token page deep-link for pump-ish
        if "pump" in qstr.lower():
            _add_token({"mint": qstr, "name": None, "symbol": None, "source": "direct"})

    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT wallet, early_buy_count, hit_rate, avg_return_pct
                    FROM wallet_performance
                    WHERE wallet ILIKE :like
                    ORDER BY early_buy_count DESC NULLS LAST
                    LIMIT :lim
                    """
                ),
                {"like": like, "lim": limit},
            )
        ).mappings().all()
        wallets = [_ser(dict(r)) for r in rows]
    except Exception:
        pass

    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT entity_id::text, primary_wallet, display_label,
                           launch_count, confidence
                    FROM entities
                    WHERE primary_wallet ILIKE :like
                       OR display_label ILIKE :like
                       OR entity_id::text ILIKE :like
                    ORDER BY launch_count DESC
                    LIMIT :lim
                    """
                ),
                {"like": like, "lim": limit},
            )
        ).mappings().all()
        entities = [_ser(dict(r)) for r in rows]
    except Exception:
        pass

    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT event_id::text, occurred_at,
                           payload->>'mint' AS mint,
                           payload->>'name' AS name,
                           (payload->>'stinky_score')::float AS stinky_score
                    FROM events
                    WHERE event_type = 'alert.candidate'
                      AND (
                        payload->>'mint' ILIKE :like
                        OR payload->>'name' ILIKE :like
                        OR payload->>'symbol' ILIKE :like
                      )
                    ORDER BY occurred_at DESC
                    LIMIT :lim
                    """
                ),
                {"like": like, "lim": limit},
            )
        ).mappings().all()
        alerts = [_ser(dict(r)) for r in rows]
    except Exception:
        pass

    return {
        "tokens": tokens,
        "wallets": wallets,
        "entities": entities,
        "alerts": alerts,
    }


async def mint_detail(session: AsyncSession, mint: str) -> dict[str, Any] | None:
    track = None
    try:
        row = (
            await session.execute(
                text("SELECT * FROM migration_tracks WHERE mint = :m"),
                {"m": mint},
            )
        ).mappings().first()
        if row:
            track = _ser(dict(row))
    except Exception:
        pass

    buyers: list[dict] = []
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT rank, wallet, sol_spent, usd_spent, bought_at, is_meaningful
                    FROM migration_buyers
                    WHERE mint = :m
                    ORDER BY rank
                    LIMIT 20
                    """
                ),
                {"m": mint},
            )
        ).mappings().all()
        buyers = [_ser(dict(r)) for r in rows]
    except Exception:
        pass

    alert = None
    try:
        row = (
            await session.execute(
                text(
                    """
                    SELECT occurred_at, payload
                    FROM events
                    WHERE event_type = 'alert.candidate'
                      AND payload->>'mint' = :m
                    ORDER BY occurred_at DESC
                    LIMIT 1
                    """
                ),
                {"m": mint},
            )
        ).mappings().first()
        if row:
            alert = {
                "occurred_at": row["occurred_at"].isoformat()
                if hasattr(row["occurred_at"], "isoformat")
                else row["occurred_at"],
                **(row["payload"] or {}),
            }
    except Exception:
        pass

    launch = None
    try:
        row = (
            await session.execute(
                text(
                    """
                    SELECT occurred_at, payload
                    FROM events
                    WHERE event_type = 'token.launch'
                      AND payload->>'mint' = :m
                    ORDER BY occurred_at DESC
                    LIMIT 1
                    """
                ),
                {"m": mint},
            )
        ).mappings().first()
        if row:
            launch = {
                "occurred_at": row["occurred_at"].isoformat()
                if hasattr(row["occurred_at"], "isoformat")
                else row["occurred_at"],
                **(row["payload"] or {}),
            }
    except Exception:
        pass

    if not track and not launch and not alert:
        inspection = await _latest_inspection(session, mint)
        if not inspection:
            return None
        return {"mint": mint, "track": None, "launch": None, "alert": None, "buyers": buyers, "inspection": inspection}

    inspection = await _latest_inspection(session, mint)
    return {
        "mint": mint,
        "track": track,
        "launch": launch,
        "alert": alert,
        "buyers": buyers,
        "inspection": inspection,
    }


async def _latest_inspection(session: AsyncSession, mint: str) -> dict[str, Any] | None:
    try:
        row = (
            await session.execute(
                text(
                    """
                    SELECT mint, inspected_at, model_version, pipeline_status,
                           gate1_passed, volume_m5_usd, synthetic_score, synthetic_level,
                           rug_score, rug_level, stinky_score, runner_potential,
                           score_confidence, fee_status, global_fees_sol,
                           has_intelligence, evidence, missing_data, alert_ok, alert_reason
                    FROM market_inspections
                    WHERE mint = :m
                    ORDER BY inspected_at DESC
                    LIMIT 1
                    """
                ),
                {"m": mint},
            )
        ).mappings().first()
        if row:
            return _ser(dict(row))
    except Exception:
        return None
    return None


def explain_wallet(row: dict[str, Any]) -> dict[str, Any]:
    """Deterministic 'why watch' from measured fields only — no invented patterns."""
    early = int(row.get("early_buy_count") or 0)
    tokens = int(row.get("tokens_purchased") or 0)
    sells = int(row.get("total_sells") or 0)
    buys = int(row.get("total_buys") or 0)
    hit = row.get("hit_rate")
    avg_ret = row.get("avg_return_pct")
    med_ret = row.get("median_return_pct")
    max_ret = row.get("max_return_pct")
    sample = sells if sells > 0 else buys
    es_rate = row.get("early_success_rate")
    es_sample = int(row.get("early_success_sample") or 0)
    on_runner = int(row.get("early_on_runner") or 0) + int(row.get("early_on_mega") or 0)
    on_fade = int(row.get("early_on_fade") or 0)

    reasons: list[str] = []
    score = 0.0

    if early >= 5:
        reasons.append(f"{early} early migration entries")
        score += min(30.0, early * 3.0)
    elif early >= 2:
        reasons.append(f"{early} early entries (building sample)")
        score += early * 4.0
    elif early == 1:
        reasons.append("Single early entry — low sample")
        score += 2.0

    if tokens >= 3:
        reasons.append(f"Active across {tokens} tokens")
        score += min(15.0, tokens * 2.0)

    # Measured success on labeled outcomes (token_outcomes → wallet_early_success)
    if es_rate is not None and es_sample >= 2:
        sr = float(es_rate)
        if sr > 1.0:
            sr = sr / 100.0
        reasons.append(
            f"Early success {sr*100:.0f}% on {es_sample} labeled tokens"
            + (f" ({on_runner} runner/mega)" if on_runner else "")
        )
        score += sr * 40.0
        if on_runner >= 2:
            score += min(15.0, on_runner * 3.0)
        if on_fade >= 3 and sr < 0.35:
            reasons.append(f"{on_fade} early fades — caution")
            score -= min(10.0, on_fade * 1.5)

    hit_f = float(hit) if hit is not None else None
    if hit_f is not None and sells >= 2:
        # normalize 0-1 or percent
        h = hit_f if hit_f <= 1.0 else hit_f / 100.0
        reasons.append(f"Hit rate {h*100:.0f}% on {sells} sells")
        score += h * 35.0
    elif sells == 0 and early > 0:
        reasons.append("No closed sells yet — entry timing only")
        score += 5.0

    if avg_ret is not None and sells >= 2:
        ar = float(avg_ret)
        reasons.append(f"Avg return {ar:+.0f}%")
        if ar > 0:
            score += min(20.0, ar / 10.0)

    if med_ret is not None and sells >= 3:
        reasons.append(f"Median return {float(med_ret):+.0f}%")

    if max_ret is not None and float(max_ret) >= 100:
        reasons.append(f"Best observed {float(max_ret):+.0f}%")

    # Confidence from sample size (not marketing)
    if (es_sample >= 5 and early >= 3) or (sample >= 10 and early >= 5):
        conf = 0.85
        tier = "high"
    elif es_sample >= 2 or sample >= 5 or early >= 3:
        conf = 0.55
        tier = "medium"
    elif early >= 1:
        conf = 0.25
        tier = "emerging"
    else:
        conf = 0.1
        tier = "thin"

    if not reasons:
        reasons.append("Insufficient measured activity")

    watch_score = max(0.0, min(100.0, score))
    return {
        **row,
        "watch_score": round(watch_score, 1),
        "watch_tier": tier,
        "watch_confidence": conf,
        "sample_size": sample,
        "why_watch": reasons,
    }


async def wallets_worth_watching(session: AsyncSession, limit: int = 50) -> list[dict]:
    rows = await top_wallets(session, limit=max(limit * 2, 40))
    enriched = [explain_wallet(r) for r in rows]
    enriched.sort(
        key=lambda r: (
            float(r.get("watch_score") or 0),
            float(r.get("early_success_rate") or 0)
            if r.get("early_success_rate") is not None
            else -1,
            int(r.get("early_on_runner") or 0) + int(r.get("early_on_mega") or 0),
            int(r.get("early_buy_count") or 0),
            float(r.get("hit_rate") or 0) if r.get("hit_rate") is not None else -1,
        ),
        reverse=True,
    )
    return enriched[:limit]


async def wallet_detail(session: AsyncSession, address: str) -> dict[str, Any] | None:
    perf = None
    try:
        row = (
            await session.execute(
                text(
                    """
                    SELECT * FROM wallet_performance WHERE wallet = :w
                    """
                ),
                {"w": address},
            )
        ).mappings().first()
        if row:
            perf = _ser(dict(row))
    except Exception:
        pass

    early_mints: list[dict] = []
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT mb.mint, mb.rank, mb.sol_spent, mb.bought_at, mb.is_meaningful,
                           mt.creator, mt.migration_at, mt.status
                    FROM migration_buyers mb
                    LEFT JOIN migration_tracks mt ON mt.mint = mb.mint
                    WHERE mb.wallet = :w
                    ORDER BY mb.bought_at DESC
                    LIMIT 40
                    """
                ),
                {"w": address},
            )
        ).mappings().all()
        early_mints = [_ser(dict(r)) for r in rows]
    except Exception:
        pass

    trades: list[dict] = []
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT mint, side, signature, traded_at, sol_amount, token_amount,
                           is_early_buyer, early_rank
                    FROM wallet_trades
                    WHERE wallet = :w
                    ORDER BY traded_at DESC
                    LIMIT 50
                    """
                ),
                {"w": address},
            )
        ).mappings().all()
        trades = [_ser(dict(r)) for r in rows]
    except Exception:
        pass

    entity = None
    try:
        row = (
            await session.execute(
                text(
                    """
                    SELECT e.entity_id::text, e.entity_type, e.primary_wallet,
                           e.launch_count, e.wallet_count, e.confidence, e.display_label,
                           ew.role, ew.link_reason
                    FROM entity_wallets ew
                    JOIN entities e ON e.entity_id = ew.entity_id
                    WHERE ew.wallet = :w
                    LIMIT 1
                    """
                ),
                {"w": address},
            )
        ).mappings().first()
        if row:
            entity = _ser(dict(row))
    except Exception:
        pass

    if not perf and not early_mints and not trades:
        return None

    base = perf or {
        "wallet": address,
        "early_buy_count": len(early_mints),
        "tokens_purchased": len({m.get("mint") for m in early_mints}),
        "total_buys": sum(1 for t in trades if t.get("side") == "buy"),
        "total_sells": sum(1 for t in trades if t.get("side") == "sell"),
    }
    if "wallet" not in base:
        base["wallet"] = address
    explained = explain_wallet(base)

    return {
        "wallet": address,
        "performance": explained,
        "entity": entity,
        "early_entries": early_mints,
        "recent_trades": trades,
        "why_watch": explained.get("why_watch") or [],
        "watch_score": explained.get("watch_score"),
        "watch_tier": explained.get("watch_tier"),
        "watch_confidence": explained.get("watch_confidence"),
    }


async def entity_detail(session: AsyncSession, entity_id: str) -> dict[str, Any] | None:
    ent = None
    try:
        row = (
            await session.execute(
                text(
                    """
                    SELECT entity_id::text, entity_type, display_label, primary_wallet,
                           wallet_count, launch_count, early_buy_count, confidence,
                           created_at, updated_at, meta
                    FROM entities
                    WHERE entity_id::text = :id
                    LIMIT 1
                    """
                ),
                {"id": entity_id},
            )
        ).mappings().first()
        if row:
            ent = _ser(dict(row))
    except Exception:
        pass

    if not ent:
        return None

    wallets: list[dict] = []
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT wallet, role, link_reason, confidence, first_seen_at, last_seen_at
                    FROM entity_wallets
                    WHERE entity_id::text = :id
                    ORDER BY role DESC, confidence DESC
                    LIMIT 50
                    """
                ),
                {"id": entity_id},
            )
        ).mappings().all()
        wallets = [_ser(dict(r)) for r in rows]
    except Exception:
        pass

    launches: list[dict] = []
    primary = ent.get("primary_wallet")
    if primary:
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT occurred_at,
                               payload->>'mint' AS mint,
                               payload->>'name' AS name,
                               payload->>'symbol' AS symbol,
                               (payload->>'stinky_score')::float AS stinky_score
                        FROM events
                        WHERE event_type = 'token.launch'
                          AND payload->>'deployer' = :w
                        ORDER BY occurred_at DESC
                        LIMIT 40
                        """
                    ),
                    {"w": primary},
                )
            ).mappings().all()
            launches = [_ser(dict(r)) for r in rows]
        except Exception:
            pass

    return {
        "entity": ent,
        "wallets": wallets,
        "launches": launches,
    }


async def discover_patterns(session: AsyncSession, limit: int = 25) -> dict[str, Any]:
    """Deterministic pattern discovery from measured store — no ML, no invention.

    Each pattern is a concrete query result with evidence counts.
    """
    patterns: list[dict[str, Any]] = []

    # 1) Repeat early buyers (same wallet early on ≥2 distinct mints)
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT wallet,
                           COUNT(DISTINCT mint)::int AS mints,
                           COUNT(*)::int AS early_entries,
                           MIN(bought_at) AS first_seen,
                           MAX(bought_at) AS last_seen
                    FROM migration_buyers
                    GROUP BY wallet
                    HAVING COUNT(DISTINCT mint) >= 2
                    ORDER BY mints DESC, early_entries DESC
                    LIMIT :lim
                    """
                ),
                {"lim": limit},
            )
        ).mappings().all()
        for r in rows:
            d = _ser(dict(r))
            patterns.append(
                {
                    "id": f"repeat_early:{d.get('wallet')}",
                    "kind": "repeat_early_buyer",
                    "title": "Repeat early buyer",
                    "summary": (
                        f"Wallet early on {d.get('mints')} migrations "
                        f"({d.get('early_entries')} ranked entries)"
                    ),
                    "confidence": min(0.95, 0.35 + 0.15 * int(d.get("mints") or 0)),
                    "evidence": d,
                    "links": {"wallet": d.get("wallet")},
                }
            )
    except Exception:
        pass

    # 2) Serial deployers (high launch_count entities)
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT entity_id::text, primary_wallet, launch_count, wallet_count,
                           confidence, display_label
                    FROM entities
                    WHERE launch_count >= 5
                    ORDER BY launch_count DESC
                    LIMIT :lim
                    """
                ),
                {"lim": limit},
            )
        ).mappings().all()
        for r in rows:
            d = _ser(dict(r))
            patterns.append(
                {
                    "id": f"serial_deployer:{d.get('entity_id')}",
                    "kind": "serial_deployer",
                    "title": "Serial deployer",
                    "summary": (
                        f"Operator with {d.get('launch_count')} stored launches "
                        f"({d.get('wallet_count') or 1} wallet(s))"
                    ),
                    "confidence": float(d.get("confidence") or 0.5),
                    "evidence": d,
                    "links": {
                        "entity_id": d.get("entity_id"),
                        "wallet": d.get("primary_wallet"),
                    },
                }
            )
    except Exception:
        pass

    # 3) High sample smart money (sells ≥3 and hit_rate available)
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT wallet, early_buy_count, total_buys, total_sells,
                           hit_rate, avg_return_pct, tokens_purchased
                    FROM wallet_performance
                    WHERE total_sells >= 3
                      AND hit_rate IS NOT NULL
                    ORDER BY hit_rate DESC NULLS LAST, total_sells DESC
                    LIMIT :lim
                    """
                ),
                {"lim": limit},
            )
        ).mappings().all()
        for r in rows:
            d = _ser(dict(r))
            hr = d.get("hit_rate")
            hr_f = float(hr) if hr is not None else 0.0
            if hr_f > 1.0:
                hr_f = hr_f / 100.0
            patterns.append(
                {
                    "id": f"measured_edge:{d.get('wallet')}",
                    "kind": "measured_edge",
                    "title": "Measured edge (closed trades)",
                    "summary": (
                        f"Hit rate {hr_f*100:.0f}% on {d.get('total_sells')} sells · "
                        f"early={d.get('early_buy_count') or 0}"
                    ),
                    "confidence": min(0.9, 0.25 + 0.1 * int(d.get("total_sells") or 0)),
                    "evidence": d,
                    "links": {"wallet": d.get("wallet")},
                }
            )
    except Exception:
        pass

    # 4) Co-buy pairs (wallets that share ≥2 mints as early buyers)
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT a.wallet AS wallet_a,
                           b.wallet AS wallet_b,
                           COUNT(DISTINCT a.mint)::int AS shared_mints
                    FROM migration_buyers a
                    JOIN migration_buyers b
                      ON a.mint = b.mint AND a.wallet < b.wallet
                    GROUP BY a.wallet, b.wallet
                    HAVING COUNT(DISTINCT a.mint) >= 2
                    ORDER BY shared_mints DESC
                    LIMIT :lim
                    """
                ),
                {"lim": min(limit, 20)},
            )
        ).mappings().all()
        for r in rows:
            d = _ser(dict(r))
            patterns.append(
                {
                    "id": f"cobuy:{d.get('wallet_a')}:{d.get('wallet_b')}",
                    "kind": "co_buy_cluster",
                    "title": "Co-buy cluster",
                    "summary": (
                        f"Two wallets early together on {d.get('shared_mints')} "
                        "migrations"
                    ),
                    "confidence": min(0.85, 0.4 + 0.1 * int(d.get("shared_mints") or 0)),
                    "evidence": d,
                    "links": {
                        "wallet": d.get("wallet_a"),
                        "wallet_b": d.get("wallet_b"),
                    },
                }
            )
    except Exception:
        pass

    # 5) Thin-capital migrations with many early buyers (possible coordinated interest)
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT mt.mint, mt.buyers_captured, mt.trades_observed, mt.migration_at,
                           mt.creator,
                           (
                             SELECT COUNT(*) FROM migration_buyers mb
                             WHERE mb.mint = mt.mint AND mb.is_meaningful
                           )::int AS meaningful_buyers
                    FROM migration_tracks mt
                    WHERE mt.buyers_captured >= 10
                    ORDER BY mt.migration_at DESC
                    LIMIT :lim
                    """
                ),
                {"lim": limit},
            )
        ).mappings().all()
        for r in rows:
            d = _ser(dict(r))
            patterns.append(
                {
                    "id": f"dense_early:{d.get('mint')}",
                    "kind": "dense_early_book",
                    "title": "Dense early book",
                    "summary": (
                        f"{d.get('buyers_captured')} early buyers captured "
                        f"({d.get('meaningful_buyers')} meaningful)"
                    ),
                    "confidence": 0.45,
                    "evidence": d,
                    "links": {"mint": d.get("mint"), "wallet": d.get("creator")},
                }
            )
    except Exception:
        pass

    # Sort by confidence then kind
    patterns.sort(key=lambda p: (float(p.get("confidence") or 0), p.get("kind") or ""), reverse=True)

    by_kind: dict[str, int] = {}
    for p in patterns:
        k = str(p.get("kind") or "other")
        by_kind[k] = by_kind.get(k, 0) + 1

    return {
        "available": True,
        "engine": "pattern-v0.1.0-deterministic",
        "message": "Patterns derived only from stored migrations, buyers, performance, entities",
        "counts_by_kind": by_kind,
        "items": patterns[: max(limit * 3, 40)],
        "total": len(patterns),
    }


async def graph_overview(
    session: AsyncSession,
    *,
    min_shared: int = 2,
    edge_limit: int = 80,
    node_limit: int = 120,
) -> dict[str, Any]:
    """Postgres-first relationship graph from measured co-buys + entity wallets.

    Nodes: wallets (and optional entity wrappers).
    Edges: co_buy (shared early mints), entity_link (same entity_id).
    """
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    # Co-buy edges
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT a.wallet AS source,
                           b.wallet AS target,
                           COUNT(DISTINCT a.mint)::int AS shared_mints,
                           MIN(LEAST(a.bought_at, b.bought_at)) AS first_shared,
                           MAX(GREATEST(a.bought_at, b.bought_at)) AS last_shared
                    FROM migration_buyers a
                    JOIN migration_buyers b
                      ON a.mint = b.mint AND a.wallet < b.wallet
                    GROUP BY a.wallet, b.wallet
                    HAVING COUNT(DISTINCT a.mint) >= :min_shared
                    ORDER BY shared_mints DESC
                    LIMIT :lim
                    """
                ),
                {"min_shared": min_shared, "lim": edge_limit},
            )
        ).mappings().all()
        for r in rows:
            d = _ser(dict(r))
            src, tgt = d.get("source"), d.get("target")
            if not src or not tgt:
                continue
            node_ids.add(src)
            node_ids.add(tgt)
            shared = int(d.get("shared_mints") or 0)
            edges.append(
                {
                    "id": f"cobuy:{src}:{tgt}",
                    "type": "co_buy",
                    "source": src,
                    "target": tgt,
                    "weight": shared,
                    "label": f"{shared} shared early mints",
                    "meta": {
                        "shared_mints": shared,
                        "first_shared": d.get("first_shared"),
                        "last_shared": d.get("last_shared"),
                    },
                }
            )
    except Exception:
        pass

    # Entity multi-wallet edges (same operator identity)
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT e.entity_id::text AS entity_id,
                           a.wallet AS source,
                           b.wallet AS target,
                           e.launch_count,
                           e.confidence
                    FROM entity_wallets a
                    JOIN entity_wallets b
                      ON a.entity_id = b.entity_id AND a.wallet < b.wallet
                    JOIN entities e ON e.entity_id = a.entity_id
                    WHERE e.wallet_count > 1
                    ORDER BY e.launch_count DESC NULLS LAST
                    LIMIT :lim
                    """
                ),
                {"lim": min(40, edge_limit)},
            )
        ).mappings().all()
        for r in rows:
            d = _ser(dict(r))
            src, tgt = d.get("source"), d.get("target")
            if not src or not tgt:
                continue
            node_ids.add(src)
            node_ids.add(tgt)
            edges.append(
                {
                    "id": f"entity:{d.get('entity_id')}:{src}:{tgt}",
                    "type": "entity_link",
                    "source": src,
                    "target": tgt,
                    "weight": int(d.get("launch_count") or 1),
                    "label": "same entity",
                    "meta": {
                        "entity_id": d.get("entity_id"),
                        "launch_count": d.get("launch_count"),
                        "confidence": d.get("confidence"),
                    },
                }
            )
    except Exception:
        pass

    # Node stats for wallets in the edge set
    nodes: list[dict[str, Any]] = []
    wallets = list(node_ids)[:node_limit]
    if wallets:
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT wallet, early_buy_count, total_buys, total_sells,
                               hit_rate, tokens_purchased
                        FROM wallet_performance
                        WHERE wallet = ANY(:w)
                        """
                    ),
                    {"w": wallets},
                )
            ).mappings().all()
            perf = {r["wallet"]: _ser(dict(r)) for r in rows}
        except Exception:
            perf = {}

        early_counts: dict[str, int] = {}
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT wallet, COUNT(DISTINCT mint)::int AS mints
                        FROM migration_buyers
                        WHERE wallet = ANY(:w)
                        GROUP BY wallet
                        """
                    ),
                    {"w": wallets},
                )
            ).mappings().all()
            early_counts = {r["wallet"]: int(r["mints"]) for r in rows}
        except Exception:
            pass

        entity_map: dict[str, dict] = {}
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT ew.wallet, e.entity_id::text, e.launch_count, e.display_label
                        FROM entity_wallets ew
                        JOIN entities e ON e.entity_id = ew.entity_id
                        WHERE ew.wallet = ANY(:w)
                        """
                    ),
                    {"w": wallets},
                )
            ).mappings().all()
            for r in rows:
                entity_map[r["wallet"]] = _ser(dict(r))
        except Exception:
            pass

        for w in wallets:
            p = perf.get(w) or {}
            em = entity_map.get(w) or {}
            degree = sum(
                1
                for e in edges
                if e.get("source") == w or e.get("target") == w
            )
            nodes.append(
                {
                    "id": w,
                    "type": "wallet",
                    "label": w[:6] + "…" + w[-4:] if len(w) > 12 else w,
                    "degree": degree,
                    "early_mints": early_counts.get(w, 0),
                    "early_buy_count": p.get("early_buy_count"),
                    "hit_rate": p.get("hit_rate"),
                    "total_sells": p.get("total_sells"),
                    "entity_id": em.get("entity_id"),
                    "launch_count": em.get("launch_count"),
                    "display_label": em.get("display_label"),
                }
            )
    else:
        # fallback: top early wallets as isolated nodes so UI is not empty
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT wallet, COUNT(DISTINCT mint)::int AS mints
                        FROM migration_buyers
                        GROUP BY wallet
                        ORDER BY mints DESC
                        LIMIT 30
                        """
                    )
                )
            ).mappings().all()
            for r in rows:
                w = r["wallet"]
                nodes.append(
                    {
                        "id": w,
                        "type": "wallet",
                        "label": w[:6] + "…" + w[-4:],
                        "degree": 0,
                        "early_mints": int(r["mints"]),
                    }
                )
        except Exception:
            pass

    nodes.sort(key=lambda n: (int(n.get("degree") or 0), int(n.get("early_mints") or 0)), reverse=True)

    return {
        "available": True,
        "engine": "graph-v0.1.0-postgres",
        "message": "Edges from co-buy overlap + multi-wallet entities (Neo4j not required)",
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "co_buy_edges": sum(1 for e in edges if e.get("type") == "co_buy"),
            "entity_edges": sum(1 for e in edges if e.get("type") == "entity_link"),
            "min_shared": min_shared,
        },
        "nodes": nodes,
        "edges": edges,
    }


async def graph_ego(
    session: AsyncSession,
    address: str,
    *,
    min_shared: int = 1,
    limit: int = 40,
) -> dict[str, Any] | None:
    """Neighborhood around one wallet."""
    neighbors: list[dict[str, Any]] = []
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT other AS neighbor,
                           COUNT(DISTINCT mint)::int AS shared_mints
                    FROM (
                      SELECT CASE WHEN wallet = :w THEN NULL ELSE wallet END AS other,
                             mint
                      FROM migration_buyers
                      WHERE mint IN (
                        SELECT mint FROM migration_buyers WHERE wallet = :w
                      )
                    ) t
                    WHERE other IS NOT NULL
                    GROUP BY other
                    HAVING COUNT(DISTINCT mint) >= :min_shared
                    ORDER BY shared_mints DESC
                    LIMIT :lim
                    """
                ),
                {"w": address, "min_shared": min_shared, "lim": limit},
            )
        ).mappings().all()
        # Fix query - the CASE approach is messy. Use clearer SQL:
    except Exception:
        rows = []

    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT b.wallet AS neighbor,
                           COUNT(DISTINCT a.mint)::int AS shared_mints
                    FROM migration_buyers a
                    JOIN migration_buyers b
                      ON a.mint = b.mint AND b.wallet <> a.wallet
                    WHERE a.wallet = :w
                    GROUP BY b.wallet
                    HAVING COUNT(DISTINCT a.mint) >= :min_shared
                    ORDER BY shared_mints DESC
                    LIMIT :lim
                    """
                ),
                {"w": address, "min_shared": min_shared, "lim": limit},
            )
        ).mappings().all()
        for r in rows:
            neighbors.append(_ser(dict(r)))
    except Exception:
        neighbors = []

    early_mints: list[dict] = []
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT mint, rank, sol_spent, bought_at
                    FROM migration_buyers
                    WHERE wallet = :w
                    ORDER BY bought_at DESC
                    LIMIT 30
                    """
                ),
                {"w": address},
            )
        ).mappings().all()
        early_mints = [_ser(dict(r)) for r in rows]
    except Exception:
        pass

    if not neighbors and not early_mints:
        return None

    return {
        "available": True,
        "wallet": address,
        "neighbor_count": len(neighbors),
        "neighbors": neighbors,
        "early_entries": early_mints,
    }


async def time_machine_wallet(
    session: AsyncSession,
    address: str,
    *,
    days: int = 90,
) -> dict[str, Any] | None:
    """Replay measured activity for a wallet over time — no invented scores.

    Points come from events (launches as deployer), migration_buyers (early entries),
    and wallet_trades (buys/sells) bucketed by day with running totals.
    """
    address = (address or "").strip()
    if not address:
        return None

    points: list[dict[str, Any]] = []
    events_out: list[dict[str, Any]] = []

    # Launches where this wallet is deployer
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT occurred_at,
                           payload->>'mint' AS mint,
                           payload->>'name' AS name,
                           payload->>'symbol' AS symbol,
                           event_type
                    FROM events
                    WHERE event_type = 'token.launch'
                      AND payload->>'deployer' = :w
                    ORDER BY occurred_at ASC
                    """
                ),
                {"w": address},
            )
        ).mappings().all()
        for r in rows:
            d = _ser(dict(r))
            events_out.append(
                {
                    "at": d.get("occurred_at"),
                    "kind": "launch",
                    "mint": d.get("mint"),
                    "name": d.get("name"),
                    "symbol": d.get("symbol"),
                }
            )
    except Exception:
        pass

    # Early buys
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT bought_at AS at, mint, rank, sol_spent
                    FROM migration_buyers
                    WHERE wallet = :w
                    ORDER BY bought_at ASC
                    """
                ),
                {"w": address},
            )
        ).mappings().all()
        for r in rows:
            d = _ser(dict(r))
            events_out.append(
                {
                    "at": d.get("at"),
                    "kind": "early_buy",
                    "mint": d.get("mint"),
                    "rank": d.get("rank"),
                    "sol_spent": d.get("sol_spent"),
                }
            )
    except Exception:
        pass

    # Trades
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT traded_at AS at, mint, side, sol_amount, is_early_buyer
                    FROM wallet_trades
                    WHERE wallet = :w
                    ORDER BY traded_at ASC
                    """
                ),
                {"w": address},
            )
        ).mappings().all()
        for r in rows:
            d = _ser(dict(r))
            events_out.append(
                {
                    "at": d.get("at"),
                    "kind": f"trade_{d.get('side') or 'unknown'}",
                    "mint": d.get("mint"),
                    "sol_amount": d.get("sol_amount"),
                    "is_early_buyer": d.get("is_early_buyer"),
                }
            )
    except Exception:
        pass

    if not events_out:
        return None

    # Sort all events
    def _key(e: dict) -> str:
        return str(e.get("at") or "")

    events_out.sort(key=_key)

    # Daily buckets with cumulative counters
    from collections import defaultdict

    daily: dict[str, dict[str, int]] = defaultdict(
        lambda: {"launches": 0, "early_buys": 0, "buys": 0, "sells": 0}
    )
    for e in events_out:
        at = e.get("at")
        if not at:
            continue
        day = str(at)[:10]
        k = e.get("kind")
        if k == "launch":
            daily[day]["launches"] += 1
        elif k == "early_buy":
            daily[day]["early_buys"] += 1
        elif k == "trade_buy":
            daily[day]["buys"] += 1
        elif k == "trade_sell":
            daily[day]["sells"] += 1

    cum_l = cum_e = cum_b = cum_s = 0
    for day in sorted(daily.keys()):
        c = daily[day]
        cum_l += c["launches"]
        cum_e += c["early_buys"]
        cum_b += c["buys"]
        cum_s += c["sells"]
        points.append(
            {
                "day": day,
                "launches": c["launches"],
                "early_buys": c["early_buys"],
                "buys": c["buys"],
                "sells": c["sells"],
                "cum_launches": cum_l,
                "cum_early_buys": cum_e,
                "cum_buys": cum_b,
                "cum_sells": cum_s,
                # Activity index: weighted measured events that day
                "activity": c["launches"] * 3 + c["early_buys"] * 2 + c["buys"] + c["sells"],
            }
        )

    # Optional entity link
    entity = None
    try:
        row = (
            await session.execute(
                text(
                    """
                    SELECT e.entity_id::text, e.display_label, e.launch_count, e.confidence
                    FROM entity_wallets ew
                    JOIN entities e ON e.entity_id = ew.entity_id
                    WHERE ew.wallet = :w
                    LIMIT 1
                    """
                ),
                {"w": address},
            )
        ).mappings().first()
        if row:
            entity = _ser(dict(row))
    except Exception:
        pass

    # Reputation curve from score_snapshots (measured only)
    score_series = await score_series_for_subject(
        session, subject_type="wallet", subject_id=address
    )
    # If empty, try soft backfill once from events for this wallet
    if not score_series:
        try:
            rows = (
                await session.execute(
                    text(
                        '''
                        SELECT occurred_at AS captured_at,
                               (payload->>'stinky_score')::float AS score,
                               (payload->>'confidence')::float AS confidence,
                               payload->>'score_model' AS model_version,
                               event_type AS context,
                               payload->>'mint' AS mint
                        FROM events
                        WHERE payload->>'stinky_score' IS NOT NULL
                          AND (
                            payload->>'deployer' = :w
                            OR payload->>'creator' = :w
                          )
                        ORDER BY occurred_at ASC
                        '''
                    ),
                    {"w": address},
                )
            ).mappings().all()
            score_series = [_ser(dict(r)) for r in rows]
        except Exception:
            score_series = []

    return {
        "score_series": score_series,
        "available": True,
        "engine": "time-machine-v0.1.0-events",
        "wallet": address,
        "entity": entity,
        "summary": {
            "event_count": len(events_out),
            "days_active": len(points),
            "launches": cum_l,
            "early_buys": cum_e,
            "buys": cum_b,
            "sells": cum_s,
            "first_at": events_out[0].get("at") if events_out else None,
            "last_at": events_out[-1].get("at") if events_out else None,
        },
        "series": points,
        "events": events_out[-200:],  # newest tail kept after sort — re-sort desc for UI
    }


async def time_machine_entity(
    session: AsyncSession,
    entity_id: str,
) -> dict[str, Any] | None:
    """Union timeline across all wallets linked to an entity."""
    wallets: list[str] = []
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT wallet FROM entity_wallets WHERE entity_id::text = :e
                    """
                ),
                {"e": entity_id},
            )
        ).mappings().all()
        wallets = [r["wallet"] for r in rows]
    except Exception:
        return None
    if not wallets:
        return None

    # Merge timelines
    merged_events: list[dict] = []
    for w in wallets:
        detail = await time_machine_wallet(session, w)
        if detail and detail.get("events"):
            for e in detail["events"]:
                e = dict(e)
                e["wallet"] = w
                merged_events.append(e)

    if not merged_events:
        # still return entity meta
        try:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT entity_id::text, primary_wallet, display_label,
                               launch_count, wallet_count, confidence
                        FROM entities WHERE entity_id::text = :e
                        """
                    ),
                    {"e": entity_id},
                )
            ).mappings().first()
            if not row:
                return None
            return {
                "available": True,
                "engine": "time-machine-v0.1.0-events",
                "entity_id": entity_id,
                "entity": _ser(dict(row)),
                "wallets": wallets,
                "summary": {"event_count": 0, "days_active": 0},
                "series": [],
                "events": [],
            }
        except Exception:
            return None

    merged_events.sort(key=lambda e: str(e.get("at") or ""))

    from collections import defaultdict

    daily: dict[str, dict[str, int]] = defaultdict(
        lambda: {"launches": 0, "early_buys": 0, "buys": 0, "sells": 0}
    )
    for e in merged_events:
        day = str(e.get("at") or "")[:10]
        if not day:
            continue
        k = e.get("kind")
        if k == "launch":
            daily[day]["launches"] += 1
        elif k == "early_buy":
            daily[day]["early_buys"] += 1
        elif k == "trade_buy":
            daily[day]["buys"] += 1
        elif k == "trade_sell":
            daily[day]["sells"] += 1

    points = []
    cum_l = cum_e = cum_b = cum_s = 0
    for day in sorted(daily.keys()):
        c = daily[day]
        cum_l += c["launches"]
        cum_e += c["early_buys"]
        cum_b += c["buys"]
        cum_s += c["sells"]
        points.append(
            {
                "day": day,
                "launches": c["launches"],
                "early_buys": c["early_buys"],
                "buys": c["buys"],
                "sells": c["sells"],
                "cum_launches": cum_l,
                "cum_early_buys": cum_e,
                "cum_buys": cum_b,
                "cum_sells": cum_s,
                "activity": c["launches"] * 3 + c["early_buys"] * 2 + c["buys"] + c["sells"],
            }
        )

    entity = None
    try:
        row = (
            await session.execute(
                text(
                    """
                    SELECT entity_id::text, primary_wallet, display_label,
                           launch_count, wallet_count, confidence
                    FROM entities WHERE entity_id::text = :e
                    """
                ),
                {"e": entity_id},
            )
        ).mappings().first()
        if row:
            entity = _ser(dict(row))
    except Exception:
        pass

    return {
        "available": True,
        "engine": "time-machine-v0.1.0-events",
        "entity_id": entity_id,
        "entity": entity,
        "wallets": wallets,
        "summary": {
            "event_count": len(merged_events),
            "days_active": len(points),
            "launches": cum_l,
            "early_buys": cum_e,
            "buys": cum_b,
            "sells": cum_s,
            "first_at": merged_events[0].get("at") if merged_events else None,
            "last_at": merged_events[-1].get("at") if merged_events else None,
        },
        "series": points,
        "events": merged_events[-300:],
    }


async def research_query(
    session: AsyncSession,
    *,
    q: str = "",
    preset: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Deterministic research over measured store — no LLM narratives.

    Presets and simple keyword routing map to the same SQL used by Patterns / Graph / Wallets.
    """
    q_raw = (q or "").strip()
    qn = q_raw.lower()
    preset = (preset or "").strip().lower() or None

    # Direct CA / mint lookup
    looks_mint = (
        32 <= len(q_raw) <= 50
        and all(
            c.isalnum() or c in "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
            for c in q_raw
        )
    )

    # Route preset / keywords
    kind = preset
    if not kind and looks_mint:
        kind = "token_lookup"
    if not kind:
        if any(w in qn for w in ("repeat", "early buyer", "multi mint", "multi-mint")):
            kind = "repeat_early"
        elif any(w in qn for w in ("serial", "deployer", "launcher", "operator")):
            kind = "serial_deployer"
        elif any(w in qn for w in ("co-buy", "cobuy", "cluster", "together")):
            kind = "co_buy"
        elif any(w in qn for w in ("hit rate", "edge", "sold", "performance", "smart")):
            kind = "measured_edge"
        elif any(w in qn for w in ("dense", "migration", "book")):
            kind = "dense_early"
        elif any(w in qn for w in ("watch", "worth watching")):
            kind = "worth_watching"
        elif any(w in qn for w in ("outcome", "precision", "alert quality", "runner rate")):
            kind = "alert_outcomes"
        else:
            kind = "overview"

    results: list[dict[str, Any]] = []
    explanation = ""

    if kind == "token_lookup":
        explanation = f"Lookup for CA {q_raw}"
        mint = q_raw
        try:
            track = (
                await session.execute(
                    text(
                        """
                        SELECT mint, pool, creator, migration_at, status,
                               buyers_captured, trades_observed
                        FROM migration_tracks WHERE mint = :m LIMIT 1
                        """
                    ),
                    {"m": mint},
                )
            ).mappings().first()
            buyers = (
                await session.execute(
                    text(
                        """
                        SELECT rank, wallet, sol_spent, bought_at
                        FROM migration_buyers WHERE mint = :m
                        ORDER BY rank ASC LIMIT 20
                        """
                    ),
                    {"m": mint},
                )
            ).mappings().all()
            snap = (
                await session.execute(
                    text(
                        """
                        SELECT volume_m5_usd, liquidity_usd, captured_at
                        FROM market_snapshots WHERE mint = :m
                        ORDER BY captured_at DESC LIMIT 1
                        """
                    ),
                    {"m": mint},
                )
            ).mappings().first()
            if track:
                d = _ser(dict(track))
                results.append(
                    {
                        "type": "token",
                        "title": "Migration track",
                        "mint": mint,
                        "summary": f"status={d.get('status')} buyers={d.get('buyers_captured')} trades={d.get('trades_observed')}",
                        "evidence": d,
                        "links": {"mint": mint, "wallet": d.get("creator")},
                    }
                )
            if snap:
                results.append(
                    {
                        "type": "market",
                        "title": "Latest market snapshot",
                        "mint": mint,
                        "summary": f"vol5m={snap.get('volume_m5_usd')} liq={snap.get('liquidity_usd')}",
                        "evidence": _ser(dict(snap)),
                        "links": {"mint": mint},
                    }
                )
            for b in buyers:
                bd = _ser(dict(b))
                results.append(
                    {
                        "type": "buyer",
                        "title": f"Early buyer rank {bd.get('rank')}",
                        "wallet": bd.get("wallet"),
                        "mint": mint,
                        "summary": f"sol={bd.get('sol_spent')}",
                        "evidence": bd,
                        "links": {"wallet": bd.get("wallet"), "mint": mint},
                    }
                )
            if not results:
                results.append(
                    {
                        "type": "token",
                        "title": "CA not in store yet",
                        "mint": mint,
                        "summary": "Open token page / Axiom — collector has not tracked this mint",
                        "links": {"mint": mint},
                    }
                )
        except Exception as exc:
            try:
                await session.rollback()
            except Exception:
                pass
            results.append(
                {
                    "type": "error",
                    "title": "Lookup failed",
                    "summary": str(exc)[:200],
                    "mint": mint,
                    "links": {"mint": mint},
                }
            )
        return {
            "available": True,
            "engine": "research-v0.1.0-deterministic",
            "kind": kind,
            "explanation": explanation,
            "query": q_raw,
            "items": results,
            "count": len(results),
        }

    if kind == "repeat_early":
        explanation = "Wallets that appear as early buyers on ≥2 distinct migrations"
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT wallet,
                               COUNT(DISTINCT mint)::int AS mints,
                               COUNT(*)::int AS entries,
                               MIN(bought_at) AS first_seen,
                               MAX(bought_at) AS last_seen
                        FROM migration_buyers
                        GROUP BY wallet
                        HAVING COUNT(DISTINCT mint) >= 2
                        ORDER BY mints DESC, entries DESC
                        LIMIT :lim
                        """
                    ),
                    {"lim": limit},
                )
            ).mappings().all()
            for r in rows:
                d = _ser(dict(r))
                results.append(
                    {
                        "type": "wallet",
                        "title": "Repeat early buyer",
                        "summary": f"{d.get('mints')} migrations · {d.get('entries')} entries",
                        "wallet": d.get("wallet"),
                        "metrics": d,
                    }
                )
        except Exception as exc:
            explanation += f" (query error: {exc})"

    elif kind == "serial_deployer":
        explanation = "Entities with the highest stored launch counts"
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT entity_id::text, primary_wallet, display_label,
                               launch_count, wallet_count, confidence
                        FROM entities
                        WHERE launch_count >= 3
                        ORDER BY launch_count DESC
                        LIMIT :lim
                        """
                    ),
                    {"lim": limit},
                )
            ).mappings().all()
            for r in rows:
                d = _ser(dict(r))
                results.append(
                    {
                        "type": "entity",
                        "title": d.get("display_label") or "Serial deployer",
                        "summary": f"{d.get('launch_count')} launches · {d.get('wallet_count') or 1} wallet(s)",
                        "wallet": d.get("primary_wallet"),
                        "entity_id": d.get("entity_id"),
                        "metrics": d,
                    }
                )
        except Exception as exc:
            explanation += f" (query error: {exc})"

    elif kind == "co_buy":
        explanation = "Wallet pairs that were early on the same migrations (≥2 shared)"
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT a.wallet AS wallet_a, b.wallet AS wallet_b,
                               COUNT(DISTINCT a.mint)::int AS shared_mints
                        FROM migration_buyers a
                        JOIN migration_buyers b
                          ON a.mint = b.mint AND a.wallet < b.wallet
                        GROUP BY a.wallet, b.wallet
                        HAVING COUNT(DISTINCT a.mint) >= 2
                        ORDER BY shared_mints DESC
                        LIMIT :lim
                        """
                    ),
                    {"lim": limit},
                )
            ).mappings().all()
            for r in rows:
                d = _ser(dict(r))
                results.append(
                    {
                        "type": "edge",
                        "title": "Co-buy cluster",
                        "summary": f"{d.get('shared_mints')} shared early mints",
                        "wallet": d.get("wallet_a"),
                        "wallet_b": d.get("wallet_b"),
                        "metrics": d,
                    }
                )
        except Exception as exc:
            explanation += f" (query error: {exc})"

    elif kind == "measured_edge":
        explanation = "Wallets with ≥3 closed sells and a stored hit rate"
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT wallet, early_buy_count, total_buys, total_sells,
                               hit_rate, avg_return_pct
                        FROM wallet_performance
                        WHERE total_sells >= 3 AND hit_rate IS NOT NULL
                        ORDER BY hit_rate DESC NULLS LAST, total_sells DESC
                        LIMIT :lim
                        """
                    ),
                    {"lim": limit},
                )
            ).mappings().all()
            for r in rows:
                d = _ser(dict(r))
                hr = d.get("hit_rate")
                hr_f = float(hr) if hr is not None else 0.0
                if hr_f > 1.0:
                    hr_f = hr_f / 100.0
                results.append(
                    {
                        "type": "wallet",
                        "title": "Measured edge",
                        "summary": (
                            f"Hit {hr_f*100:.0f}% · {d.get('total_sells')} sells · "
                            f"early={d.get('early_buy_count') or 0}"
                        ),
                        "wallet": d.get("wallet"),
                        "metrics": d,
                    }
                )
        except Exception as exc:
            explanation += f" (query error: {exc})"

    elif kind == "dense_early":
        explanation = "Migrations with the densest early-buyer books"
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT mint, buyers_captured, trades_observed, migration_at, creator,
                               (
                                 SELECT COUNT(*) FROM migration_buyers mb
                                 WHERE mb.mint = mt.mint AND mb.is_meaningful
                               )::int AS meaningful_buyers
                        FROM migration_tracks mt
                        WHERE buyers_captured >= 8
                        ORDER BY buyers_captured DESC, migration_at DESC
                        LIMIT :lim
                        """
                    ),
                    {"lim": limit},
                )
            ).mappings().all()
            for r in rows:
                d = _ser(dict(r))
                results.append(
                    {
                        "type": "mint",
                        "title": "Dense early book",
                        "summary": (
                            f"{d.get('buyers_captured')} early · "
                            f"{d.get('meaningful_buyers')} meaningful"
                        ),
                        "mint": d.get("mint"),
                        "wallet": d.get("creator"),
                        "metrics": d,
                    }
                )
        except Exception as exc:
            explanation += f" (query error: {exc})"

    elif kind == "worth_watching":
        explanation = "Wallets ranked by early-entry sample (from wallet_performance)"
        try:
            # reuse logic similar to wallets_worth_watching if present
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT wallet, early_buy_count, total_buys, total_sells,
                               hit_rate, avg_return_pct, tokens_purchased
                        FROM wallet_performance
                        WHERE early_buy_count > 0 OR total_sells > 0
                        ORDER BY early_buy_count DESC NULLS LAST,
                                 total_sells DESC NULLS LAST
                        LIMIT :lim
                        """
                    ),
                    {"lim": limit},
                )
            ).mappings().all()
            for r in rows:
                d = _ser(dict(r))
                results.append(
                    {
                        "type": "wallet",
                        "title": "Worth watching",
                        "summary": (
                            f"early={d.get('early_buy_count') or 0} · "
                            f"sells={d.get('total_sells') or 0}"
                        ),
                        "wallet": d.get("wallet"),
                        "metrics": d,
                    }
                )
        except Exception as exc:
            explanation += f" (query error: {exc})"


    elif kind == "alert_outcomes":
        explanation = "Gated alert outcomes measured against market_snapshots"
        out = await alert_outcomes(session, limit=limit, recompute=True)
        for it in out.get("items") or []:
            results.append(
                {
                    "type": "alert",
                    "title": it.get("label") or "alert",
                    "summary": (
                        f"score={it.get('score')} · vol5m={it.get('volume_m5_usd')} · "
                        f"mult={it.get('volume_multiple')} · {it.get('notes') or ''}"
                    ),
                    "mint": it.get("mint"),
                    "wallet": it.get("deployer"),
                    "metrics": it,
                }
            )
        if out.get("runner_rate") is not None:
            explanation += f" · runner_rate={out['runner_rate']:.0%}"

    else:  # overview
        explanation = "Store snapshot — use a preset or keywords for a focused query"
        try:
            stats = {}
            for label, sql in [
                ("migration_buyers", "SELECT COUNT(*)::int AS n FROM migration_buyers"),
                ("entities", "SELECT COUNT(*)::int AS n FROM entities"),
                ("wallet_performance", "SELECT COUNT(*)::int AS n FROM wallet_performance"),
                ("migrations_tracked", "SELECT COUNT(*)::int AS n FROM migration_tracks"),
            ]:
                try:
                    n = (await session.execute(text(sql))).scalar()
                    stats[label] = int(n or 0)
                except Exception:
                    stats[label] = None
            results.append(
                {
                    "type": "meta",
                    "title": "Intelligence store",
                    "summary": "Current measured inventory",
                    "metrics": stats,
                }
            )
        except Exception:
            pass

    return {
        "available": True,
        "engine": "research-v0.1.0-deterministic",
        "kind": kind,
        "query": q,
        "preset": preset,
        "explanation": explanation,
        "count": len(results),
        "items": results,
        "presets": [
            {"id": "repeat_early", "label": "Repeat early buyers"},
            {"id": "serial_deployer", "label": "Serial deployers"},
            {"id": "co_buy", "label": "Co-buy clusters"},
            {"id": "measured_edge", "label": "Measured edge"},
            {"id": "dense_early", "label": "Dense early books"},
            {"id": "worth_watching", "label": "Worth watching"},
            {"id": "overview", "label": "Store overview"},
            {"id": "alert_outcomes", "label": "Alert outcomes"},
        ],
    }



async def ensure_alert_outcomes_schema(session: AsyncSession) -> None:
    """Idempotent schema for alert_log + alert_outcomes."""
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS alert_log (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                mint TEXT NOT NULL,
                alerted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                score DOUBLE PRECISION,
                confidence DOUBLE PRECISION,
                volume_m5_usd DOUBLE PRECISION,
                meaningful_buyers INT,
                entity_launch_count INT,
                score_model TEXT,
                name TEXT,
                symbol TEXT,
                deployer TEXT,
                dm_sent BOOLEAN NOT NULL DEFAULT TRUE,
                channel_posted BOOLEAN NOT NULL DEFAULT FALSE,
                payload JSONB
            )
            """
        )
    )
    await session.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_alert_log_mint_time
            ON alert_log (mint, alerted_at DESC)
            """
        )
    )
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS alert_outcomes (
                alert_id UUID PRIMARY KEY,
                mint TEXT NOT NULL,
                evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                hours_since DOUBLE PRECISION,
                peak_volume_m5_usd DOUBLE PRECISION,
                peak_liquidity_usd DOUBLE PRECISION,
                peak_price_usd DOUBLE PRECISION,
                last_volume_m5_usd DOUBLE PRECISION,
                snapshots_n INT NOT NULL DEFAULT 0,
                volume_multiple DOUBLE PRECISION,
                label TEXT,
                notes TEXT
            )
            """
        )
    )
    await session.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_alert_outcomes_label
            ON alert_outcomes (label)
            """
        )
    )
    await session.commit()


async def seed_alert_log_from_events(
    session: AsyncSession, *, limit: int = 500
) -> int:
    """Insert alert.candidate events into alert_log (one row per event_id).

    Measured only — does not invent alerts.
    """
    await ensure_alert_outcomes_schema(session)
    try:
        result = await session.execute(
            text(
                """
                INSERT INTO alert_log (
                    id, mint, alerted_at, score, confidence, volume_m5_usd,
                    meaningful_buyers, name, symbol, deployer, score_model,
                    dm_sent, channel_posted, payload
                )
                SELECT
                    e.event_id,
                    e.payload->>'mint',
                    e.occurred_at,
                    NULLIF(e.payload->>'stinky_score', '')::float,
                    NULLIF(e.payload->>'confidence', '')::float,
                    NULLIF(e.payload->>'volume_m5_usd', '')::float,
                    NULLIF(e.payload->>'meaningful_buyer_count', '')::int,
                    e.payload->>'name',
                    e.payload->>'symbol',
                    COALESCE(e.payload->>'deployer', e.payload->>'creator'),
                    e.payload->>'score_model',
                    TRUE,
                    FALSE,
                    e.payload
                FROM events e
                WHERE e.event_type = 'alert.candidate'
                  AND e.payload->>'mint' IS NOT NULL
                ORDER BY e.occurred_at DESC
                LIMIT :lim
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"lim": limit},
        )
        await session.commit()
        return int(result.rowcount or 0)
    except Exception:
        await session.rollback()
        # Fallback without ordering subquery limits if planner issues
        try:
            result = await session.execute(
                text(
                    """
                    INSERT INTO alert_log (
                        id, mint, alerted_at, score, confidence, volume_m5_usd,
                        meaningful_buyers, name, symbol, deployer, dm_sent, payload
                    )
                    SELECT
                        e.event_id,
                        e.payload->>'mint',
                        e.occurred_at,
                        NULLIF(e.payload->>'stinky_score', '')::float,
                        NULLIF(e.payload->>'confidence', '')::float,
                        NULLIF(e.payload->>'volume_m5_usd', '')::float,
                        NULLIF(e.payload->>'meaningful_buyer_count', '')::int,
                        e.payload->>'name',
                        e.payload->>'symbol',
                        COALESCE(e.payload->>'deployer', e.payload->>'creator'),
                        TRUE,
                        e.payload
                    FROM events e
                    WHERE e.event_type = 'alert.candidate'
                      AND e.payload->>'mint' IS NOT NULL
                    ON CONFLICT (id) DO NOTHING
                    """
                )
            )
            await session.commit()
            return int(result.rowcount or 0)
        except Exception:
            await session.rollback()
            return 0


async def alert_outcomes(
    session: AsyncSession,
    *,
    limit: int = 50,
    recompute: bool = True,
) -> dict[str, Any]:
    """Evaluate gated alerts against market_snapshots (measured only).

    Labels:
      - runner: peak volume_m5 >= 2x alert volume OR peak >= $100k
      - held: still has snapshots after 1h with volume >= 50% of alert
      - fade: peak volume never exceeded alert volume materially
      - unknown: no snapshots yet
    """
    seeded = 0
    try:
        await ensure_alert_outcomes_schema(session)
        seeded = await seed_alert_log_from_events(session, limit=max(limit * 4, 200))
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass

    alerts = []
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id::text, mint, alerted_at, score, confidence,
                           volume_m5_usd, meaningful_buyers, name, symbol, deployer
                    FROM alert_log
                    ORDER BY alerted_at DESC
                    LIMIT :lim
                    """
                ),
                {"lim": limit},
            )
        ).mappings().all()
        alerts = [dict(r) for r in rows]
    except Exception as exc:
        return {
            "available": True,
            "engine": "outcomes-v0.2.0-auto-label",
            "message": f"alert_log empty or missing: {exc}",
            "counts": {},
            "items": [],
            "seeded_from_events": seeded,
        }

    if recompute:
        for a in alerts:
            mint = a["mint"]
            alerted = a["alerted_at"]
            base_vol = float(a["volume_m5_usd"] or 0)
            try:
                snap = (
                    await session.execute(
                        text(
                            """
                            SELECT
                              COUNT(*)::int AS n,
                              MAX(volume_m5_usd) AS peak_vol,
                              MAX(liquidity_usd) AS peak_liq,
                              MAX(price_usd) AS peak_px,
                              (ARRAY_AGG(volume_m5_usd ORDER BY captured_at DESC))[1] AS last_vol
                            FROM market_snapshots
                            WHERE mint = :m AND captured_at >= :t
                            """
                        ),
                        {"m": mint, "t": alerted},
                    )
                ).mappings().first()
            except Exception:
                # column names may differ
                try:
                    snap = (
                        await session.execute(
                            text(
                                """
                                SELECT COUNT(*)::int AS n,
                                       MAX(volume_m5_usd) AS peak_vol,
                                       MAX(liquidity_usd) AS peak_liq,
                                       MAX(price_usd) AS peak_px,
                                       NULL::float AS last_vol
                                FROM market_snapshots
                                WHERE mint = :m
                                """
                            ),
                            {"m": mint},
                        )
                    ).mappings().first()
                except Exception:
                    snap = None

            n = int((snap or {}).get("n") or 0)
            peak = float((snap or {}).get("peak_vol") or 0) if snap else 0.0
            peak_liq = float((snap or {}).get("peak_liq") or 0) if snap and snap.get("peak_liq") is not None else None
            peak_px = float((snap or {}).get("peak_px") or 0) if snap and snap.get("peak_px") is not None else None
            last_vol = float((snap or {}).get("last_vol") or 0) if snap and snap.get("last_vol") is not None else None
            mult = (peak / base_vol) if base_vol > 0 and peak > 0 else None

            if n == 0:
                label, notes = "unknown", "no market_snapshots after alert"
            elif mult is not None and (mult >= 2.0 or peak >= 100_000):
                label, notes = "runner", f"peak_vol={peak:.0f} mult={mult:.2f}"
            elif last_vol is not None and base_vol > 0 and last_vol >= base_vol * 0.5:
                label, notes = "held", f"last_vol={last_vol:.0f}"
            else:
                label, notes = "fade", f"peak_vol={peak:.0f}"

            try:
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                at = alerted
                if hasattr(at, "tzinfo") and at.tzinfo is None:
                    at = at.replace(tzinfo=timezone.utc)
                hours = (now - at).total_seconds() / 3600.0 if at else None
            except Exception:
                hours = None

            try:
                await session.execute(
                    text(
                        """
                        INSERT INTO alert_outcomes (
                            alert_id, mint, hours_since, peak_volume_m5_usd,
                            peak_liquidity_usd, peak_price_usd, last_volume_m5_usd,
                            snapshots_n, volume_multiple, label, notes, evaluated_at
                        ) VALUES (
                            CAST(:id AS uuid), :mint, :hrs, :peak,
                            :pli, :ppx, :last,
                            :n, :mult, :label, :notes, now()
                        )
                        ON CONFLICT (alert_id) DO UPDATE SET
                            hours_since = EXCLUDED.hours_since,
                            peak_volume_m5_usd = EXCLUDED.peak_volume_m5_usd,
                            peak_liquidity_usd = EXCLUDED.peak_liquidity_usd,
                            peak_price_usd = EXCLUDED.peak_price_usd,
                            last_volume_m5_usd = EXCLUDED.last_volume_m5_usd,
                            snapshots_n = EXCLUDED.snapshots_n,
                            volume_multiple = EXCLUDED.volume_multiple,
                            label = EXCLUDED.label,
                            notes = EXCLUDED.notes,
                            evaluated_at = now()
                        """
                    ),
                    {
                        "id": a["id"],
                        "mint": mint,
                        "hrs": hours,
                        "peak": peak or None,
                        "pli": peak_liq,
                        "ppx": peak_px,
                        "last": last_vol,
                        "n": n,
                        "mult": mult,
                        "label": label,
                        "notes": notes,
                    },
                )
                await session.commit()
            except Exception as exc:
                await session.rollback()
                logger_msg = str(exc)

    # Summary + join
    items = []
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT a.id::text, a.mint, a.alerted_at, a.score, a.volume_m5_usd,
                           a.meaningful_buyers, a.name, a.symbol, a.deployer,
                           o.label, o.volume_multiple, o.peak_volume_m5_usd,
                           o.snapshots_n, o.hours_since, o.notes
                    FROM alert_log a
                    LEFT JOIN alert_outcomes o ON o.alert_id = a.id
                    ORDER BY a.alerted_at DESC
                    LIMIT :lim
                    """
                ),
                {"lim": limit},
            )
        ).mappings().all()
        items = [_ser(dict(r)) for r in rows]
    except Exception:
        items = [_ser(a) for a in alerts]

    counts: dict[str, int] = {}
    for it in items:
        lab = it.get("label") or "unknown"
        counts[lab] = counts.get(lab, 0) + 1

    total = len(items)
    runners = counts.get("runner", 0)
    fades = counts.get("fade", 0)
    held = counts.get("held", 0)
    unknown = counts.get("unknown", 0)
    precision = (runners / total) if total else None
    fade_rate = (fades / total) if total else None

    # Unique-mint precision (latest label per mint)
    unique_mints = len({it.get("mint") for it in items if it.get("mint")})
    by_mint: dict[str, str] = {}
    for it in items:
        m = it.get("mint")
        if not m or m in by_mint:
            continue
        by_mint[str(m)] = str(it.get("label") or "unknown")
    unique_runners = sum(1 for lab in by_mint.values() if lab == "runner")
    unique_rate = (unique_runners / len(by_mint)) if by_mint else None

    return {
        "available": True,
        "engine": "outcomes-v0.2.0-auto-label",
        "counts": counts,
        "total_alerts": total,
        "total_unique_mints": unique_mints,
        "runner_rate": precision,
        "fade_rate": fade_rate,
        "precision_runner": unique_rate if unique_rate is not None else precision,
        "runners_among_passed": runners,
        "held": held,
        "unknown": unknown,
        "seeded_from_events": seeded,
        "source": "alert_log+market_snapshots",
        "items": items,
    }


async def ensure_score_snapshots_schema(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS score_snapshots (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                score DOUBLE PRECISION NOT NULL,
                confidence DOUBLE PRECISION,
                model_version TEXT,
                context TEXT,
                mint TEXT,
                explanation JSONB,
                signals JSONB,
                captured_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    await session.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_score_snap_subject
            ON score_snapshots (subject_type, subject_id, captured_at DESC)
            """
        )
    )
    await session.commit()


async def record_score_snapshot(
    session: AsyncSession,
    *,
    subject_type: str,
    subject_id: str,
    score: float,
    confidence: float | None = None,
    model_version: str | None = None,
    context: str | None = None,
    mint: str | None = None,
    explanation: Any = None,
    signals: Any = None,
) -> None:
    import json
    await ensure_score_snapshots_schema(session)
    await session.execute(
        text(
            """
            INSERT INTO score_snapshots (
                subject_type, subject_id, score, confidence, model_version,
                context, mint, explanation, signals
            ) VALUES (
                :st, :sid, :score, :conf, :model,
                :ctx, :mint, CAST(:expl AS jsonb), CAST(:sig AS jsonb)
            )
            """
        ),
        {
            "st": subject_type,
            "sid": subject_id,
            "score": score,
            "conf": confidence,
            "model": model_version,
            "ctx": context,
            "mint": mint,
            "expl": json.dumps(explanation) if explanation is not None else None,
            "sig": json.dumps(signals) if signals is not None else None,
        },
    )
    await session.commit()


async def backfill_score_snapshots_from_events(
    session: AsyncSession, *, limit: int = 5000
) -> dict[str, int]:
    """Seed score_snapshots from historical alert.candidate / token.launch events."""
    await ensure_score_snapshots_schema(session)
    inserted = 0
    # Avoid dupes: skip if we already have any snapshots
    try:
        n = (
            await session.execute(text("SELECT COUNT(*)::int FROM score_snapshots"))
        ).scalar()
        if n and int(n) > 0:
            return {"inserted": 0, "skipped": "already_seeded", "existing": int(n)}
    except Exception:
        pass

    rows = (
        await session.execute(
            text(
                """
                SELECT occurred_at,
                       event_type,
                       payload->>'mint' AS mint,
                       payload->>'deployer' AS deployer,
                       payload->>'creator' AS creator,
                       (payload->>'stinky_score')::float AS score,
                       (payload->>'confidence')::float AS confidence,
                       payload->>'score_model' AS model_version,
                       payload->'score_explanation' AS explanation
                FROM events
                WHERE payload->>'stinky_score' IS NOT NULL
                  AND event_type IN ('alert.candidate', 'token.launch')
                ORDER BY occurred_at ASC
                LIMIT :lim
                """
            ),
            {"lim": limit},
        )
    ).mappings().all()

    import json
    for r in rows:
        score = r.get("score")
        if score is None:
            continue
        wallet = r.get("deployer") or r.get("creator")
        mint = r.get("mint")
        ctx = "backfill_alert" if r.get("event_type") == "alert.candidate" else "backfill_launch"
        expl = r.get("explanation")
        if expl is not None and not isinstance(expl, str):
            try:
                expl = json.dumps(expl)
            except Exception:
                expl = None
        try:
            if wallet:
                await session.execute(
                    text(
                        """
                        INSERT INTO score_snapshots (
                            subject_type, subject_id, score, confidence, model_version,
                            context, mint, explanation, captured_at
                        ) VALUES (
                            'wallet', :sid, :score, :conf, :model,
                            :ctx, :mint, CAST(:expl AS jsonb), :at
                        )
                        """
                    ),
                    {
                        "sid": wallet,
                        "score": float(score),
                        "conf": r.get("confidence"),
                        "model": r.get("model_version"),
                        "ctx": ctx,
                        "mint": mint,
                        "expl": expl if isinstance(expl, str) else None,
                        "at": r.get("occurred_at"),
                    },
                )
                inserted += 1
            if mint:
                await session.execute(
                    text(
                        """
                        INSERT INTO score_snapshots (
                            subject_type, subject_id, score, confidence, model_version,
                            context, mint, explanation, captured_at
                        ) VALUES (
                            'mint', :sid, :score, :conf, :model,
                            :ctx, :mint, CAST(:expl AS jsonb), :at
                        )
                        """
                    ),
                    {
                        "sid": mint,
                        "score": float(score),
                        "conf": r.get("confidence"),
                        "model": r.get("model_version"),
                        "ctx": ctx,
                        "mint": mint,
                        "expl": expl if isinstance(expl, str) else None,
                        "at": r.get("occurred_at"),
                    },
                )
                inserted += 1
        except Exception:
            await session.rollback()
            continue
    try:
        await session.commit()
    except Exception:
        await session.rollback()
    return {"inserted": inserted}


async def score_series_for_subject(
    session: AsyncSession,
    *,
    subject_type: str,
    subject_id: str,
) -> list[dict[str, Any]]:
    try:
        await ensure_score_snapshots_schema(session)
        rows = (
            await session.execute(
                text(
                    """
                    SELECT captured_at, score, confidence, model_version,
                           context, mint, explanation
                    FROM score_snapshots
                    WHERE subject_type = :st AND subject_id = :sid
                    ORDER BY captured_at ASC
                    """
                ),
                {"st": subject_type, "sid": subject_id},
            )
        ).mappings().all()
        return [_ser(dict(r)) for r in rows]
    except Exception:
        return []



async def multi_wallet_entities(session: AsyncSession, limit: int = 30) -> list[dict]:
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT entity_id::text, entity_type, display_label, primary_wallet,
                           wallet_count, launch_count, early_buy_count, confidence,
                           updated_at
                    FROM entities
                    WHERE wallet_count > 1
                      AND COALESCE(meta->>'status', '') <> 'merged'
                    ORDER BY wallet_count DESC, launch_count DESC
                    LIMIT :lim
                    """
                ),
                {"lim": limit},
            )
        ).mappings().all()
        return [_ser(dict(r)) for r in rows]
    except Exception:
        return []


async def replay_funnel(session: AsyncSession) -> dict[str, Any]:
    try:
        mig = (
            await session.execute(
                text(
                    "SELECT COUNT(DISTINCT payload->>'mint')::int FROM events WHERE event_type = 'token.migrated'"
                )
            )
        ).scalar() or 0
        tracks = (
            await session.execute(text("SELECT COUNT(*)::int FROM migration_tracks"))
        ).scalar() or 0
        with_buyers = (
            await session.execute(
                text("SELECT COUNT(DISTINCT mint)::int FROM migration_buyers")
            )
        ).scalar() or 0
        alerts = (
            await session.execute(
                text(
                    "SELECT COUNT(DISTINCT payload->>'mint')::int FROM events WHERE event_type = 'alert.candidate'"
                )
            )
        ).scalar() or 0
        mig, tracks, with_buyers, alerts = int(mig), int(tracks), int(with_buyers), int(alerts)
        return {
            "engine": "replay-v0.1.0-funnel",
            "migrations": mig,
            "tracks": tracks,
            "mints_with_buyers": with_buyers,
            "alert_candidates": alerts,
            "track_rate": (tracks / mig) if mig else None,
            "buyer_rate": (with_buyers / tracks) if tracks else None,
            "alert_rate": (alerts / with_buyers) if with_buyers else None,
        }
    except Exception as exc:
        return {"engine": "replay-v0.1.0-funnel", "error": str(exc)}


async def replay_score_gate_backtest(
    session: AsyncSession, *, min_score: float = 55.0, limit: int = 200
) -> dict[str, Any]:
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT occurred_at, payload->>'mint' AS mint,
                           (payload->>'stinky_score')::float AS score,
                           (payload->>'volume_m5_usd')::float AS volume_m5_usd
                    FROM events
                    WHERE event_type = 'alert.candidate'
                      AND payload->>'stinky_score' IS NOT NULL
                    ORDER BY occurred_at DESC
                    LIMIT :lim
                    """
                ),
                {"lim": limit},
            )
        ).mappings().all()
    except Exception as exc:
        return {"engine": "replay-v0.1.0-score-gate", "error": str(exc)}

    passed = runners = fades = unknown = 0
    items = []
    seen_mints: set[str] = set()
    for r in rows:
        score = r.get("score")
        mint = r.get("mint")
        if score is None or not mint:
            continue
        if mint in seen_mints:
            continue
        seen_mints.add(mint)
        gate = float(score) >= min_score
        if gate:
            passed += 1
        peak = None
        snap_n = 0
        try:
            pr = (
                await session.execute(
                    text(
                        """
                        SELECT MAX(volume_m5_usd) AS peak, COUNT(*)::int AS n
                        FROM market_snapshots
                        WHERE mint = :m AND captured_at >= :at
                        """
                    ),
                    {"m": mint, "at": r["occurred_at"]},
                )
            ).mappings().first()
            if pr:
                peak = pr.get("peak")
                snap_n = int(pr.get("n") or 0)
        except Exception:
            pass
        label = "unknown"
        if snap_n and peak is not None:
            vol0 = r.get("volume_m5_usd")
            mult = (float(peak) / float(vol0)) if vol0 else None
            if (mult is not None and mult >= 2.0) or float(peak) >= 100_000:
                label = "runner"
                if gate:
                    runners += 1
            else:
                label = "fade"
                if gate:
                    fades += 1
        else:
            if gate:
                unknown += 1
        items.append(
            {
                "mint": mint,
                "score": score,
                "gate_pass": gate,
                "label": label,
                "peak_volume_m5_usd": peak,
            }
        )
    return {
        "engine": "replay-v0.1.0-score-gate",
        "min_score": min_score,
        "candidates": len(items),
        "gate_passed": passed,
        "runners_among_passed": runners,
        "fades_among_passed": fades,
        "unknown_among_passed": unknown,
        "precision_runner": (runners / passed) if passed else None,
        "items": items[:40],
    }


async def alert_precision_summary(session: AsyncSession) -> dict[str, Any]:
    """Unique-mint score-gate precision for Command Center (measured only)."""
    try:
        # Prefer alert_outcomes if populated
        rows = (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT ON (a.mint)
                           a.mint, a.score, o.label, a.alerted_at
                    FROM alert_log a
                    LEFT JOIN alert_outcomes o ON o.alert_id = a.id
                    ORDER BY a.mint, a.alerted_at DESC
                    """
                )
            )
        ).mappings().all()
        if not rows:
            # Fallback: unique alert.candidate from events + snapshots
            return await replay_score_gate_backtest(session, min_score=55.0, limit=100)

        counts: dict[str, int] = {}
        total = 0
        for r in rows:
            total += 1
            lab = r.get("label") or "unknown"
            counts[lab] = counts.get(lab, 0) + 1
        runners = counts.get("runner", 0)
        return {
            "available": True,
            "engine": "precision-v0.1.0-unique-mint",
            "total_unique_mints": total,
            "counts": counts,
            "runner_rate": (runners / total) if total else None,
            "source": "alert_log",
        }
    except Exception:
        try:
            return await replay_score_gate_backtest(session, min_score=55.0, limit=100)
        except Exception as exc:
            return {"available": False, "error": str(exc)}


async def load_memory_snapshot(session: AsyncSession) -> dict[str, Any]:
    """Hydrate IntelligenceMemory from Postgres. Missing tables stay empty. Never invented."""
    from stinky_core.memory import (
        MEMORY_SELECT_CREATOR_OBS,
        MEMORY_SELECT_CREATOR_OUTCOME,
        MEMORY_SELECT_DECISION,
        MEMORY_SELECT_FINGERPRINT,
        MEMORY_SELECT_FINGERPRINT_OUTCOME,
        MEMORY_SELECT_INVESTIGATION,
        MEMORY_SELECT_MARKET_OBS,
        MEMORY_SELECT_QUALITY,
        MEMORY_SELECT_WALLET_OBS,
        MEMORY_SELECT_WALLET_OUTCOME,
        MEMORY_SELECT_OPERATOR_EVENT,
        MEMORY_SELECT_WATCH_STATE,
        MEMORY_SELECT_PROVIDER_PROBE,
        MEMORY_SELECT_DISCORD_DELIVERY,
    )

    def _clean(row: Any) -> dict[str, Any]:
        d = dict(row)
        for k, v in list(d.items()):
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        return d

    async def rows(sql: str) -> list[dict[str, Any]]:
        try:
            found = (await session.execute(text(sql))).mappings().all()
            return [_clean(r) for r in found]
        except Exception:
            return []

    return {
        "wallet_obs": await rows(MEMORY_SELECT_WALLET_OBS),
        "wallet_outcomes": await rows(MEMORY_SELECT_WALLET_OUTCOME),
        "creator_obs": await rows(MEMORY_SELECT_CREATOR_OBS),
        "creator_outcomes": await rows(MEMORY_SELECT_CREATOR_OUTCOME),
        "fingerprints": await rows(MEMORY_SELECT_FINGERPRINT),
        "fingerprint_outcomes": await rows(MEMORY_SELECT_FINGERPRINT_OUTCOME),
        "decisions": await rows(MEMORY_SELECT_DECISION),
        "market_ticks": await rows(MEMORY_SELECT_MARKET_OBS),
        "investigations": await rows(MEMORY_SELECT_INVESTIGATION),
        "quality_states": await rows(MEMORY_SELECT_QUALITY),
        "operator_events": await rows(MEMORY_SELECT_OPERATOR_EVENT),
        "watch_states": await rows(MEMORY_SELECT_WATCH_STATE),
        "provider_probes": await rows(MEMORY_SELECT_PROVIDER_PROBE),
        "discord_deliveries": await rows(MEMORY_SELECT_DISCORD_DELIVERY),
    }
