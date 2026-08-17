"""5-minute volume gate for migrated tokens.

Uses DexScreener (no API key) to read volume.m5 USD after migration.
When volume_m5 >= threshold, emits ALERT_CANDIDATE for downstream Discord.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from stinky_core.events.base import Event, EventType

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sentinel.config import settings
from sentinel.models import DetectedMigration
from sentinel.publisher import LaunchPublisher
from sentinel.qualify import qualify_fresh_pump_migration
from sentinel.score import EntitySignals, SmartMoneySignals, score_alert_candidate

logger = structlog.get_logger(__name__)

def _allowed_dexes() -> set[str]:
    raw = getattr(settings, "allowed_dex_ids", "pumpswap,pumpfun,pump") or ""
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def _denied_dexes() -> set[str]:
    raw = getattr(settings, "denied_dex_ids", "meteora,raydium,orca") or ""
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def _dex_allowed(dex_id: str | None) -> bool:
    if not dex_id:
        return False
    d = str(dex_id).lower()
    if d in _denied_dexes():
        return False
    allow = _allowed_dexes()
    if not allow:
        return True
    return d in allow or any(a in d for a in allow)


def _is_pump_mint(mint: str) -> bool:
    if not getattr(settings, "require_pump_mint_suffix", True):
        return True
    return mint.lower().endswith("pump")


def _birdeye_api_key() -> str | None:
    """Read Birdeye key from settings or env. Never log the value."""
    import os
    for name in ("birdeye_api_key", "BIRDEYE_API_KEY", "STINKY_BIRDEYE_API_KEY"):
        v = getattr(settings, name, None) if not name.isupper() else None
        if not v:
            v = os.environ.get(name) or os.environ.get(name.upper())
        if v and str(v).strip() and str(v).strip() not in ("changeme", "your_key_here"):
            return str(v).strip()
    return None


def _parse_fee_number(val: object) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f != f or f < 0:  # NaN / negative
        return None
    # lamports-scale safety
    if f > 1_000_000:
        f = f / 1_000_000_000.0
    return f


async def fetch_pump_fees_sol(client: httpx.AsyncClient, mint: str) -> float | None:
    """Authoritative global fees paid (SOL) via Birdeye; fail-closed if unavailable.

    Sources (in order):
      1) GET /defi/v3/token/fee/single?address=&intervals=alltime
      2) GET /defi/v3/token/meme/detail/single?address=
      3) GET /defi/token_overview?address=

    Requires BIRDEYE_API_KEY / STINKY_BIRDEYE_API_KEY. Missing key or missing field -> None.
    """
    key = _birdeye_api_key()
    if not key:
        logger.warning("fees.birdeye_key_missing mint=%s", mint)
        return None

    headers = {
        "Accept": "application/json",
        "X-API-KEY": key,
        "x-chain": "solana",
    }
    # Order matters: many plans allow meme/detail + token_overview but not fee/single.
    urls = [
        (
            f"https://public-api.birdeye.so/defi/v3/token/meme/detail/single?address={mint}",
            ("data",),
        ),
        (
            f"https://public-api.birdeye.so/defi/token_overview?address={mint}",
            ("data",),
        ),
        (
            f"https://public-api.birdeye.so/defi/v3/token/fee/single?address={mint}&intervals=alltime",
            ("data",),
        ),
    ]
    for url, nests in urls:
        try:
            resp = await client.get(url, timeout=10.0, headers=headers)
            if resp.status_code in (401, 403):
                # Plan may allow meme/overview but not fee/single ? try next endpoint
                logger.warning(
                    "fees.birdeye_endpoint_denied",
                    status=resp.status_code,
                    path=url.split("?")[0],
                )
                continue
            if resp.status_code == 429:
                logger.warning("fees.birdeye_rate_limited mint=%s", mint)
                continue
            if resp.status_code != 200:
                continue
            payload = resp.json()
            if not isinstance(payload, dict):
                continue
            nodes: list[object] = [payload]
            data = payload.get("data")
            if isinstance(data, dict):
                nodes.append(data)
                # fee/single may nest alltime
                for subk in ("alltime", "fee", "fees", "overview"):
                    sub = data.get(subk)
                    if isinstance(sub, dict):
                        nodes.append(sub)
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                for key_name in (
                    "global_fees_paid",
                    "globalFeesPaid",
                    "fees_paid",
                    "total_fees",
                    "total_fees_sol",
                    "fees_sol",
                ):
                    if key_name in node and node[key_name] is not None:
                        parsed = _parse_fee_number(node[key_name])
                        if parsed is not None:
                            logger.info(
                                "fees.birdeye_ok",
                                mint=mint,
                                global_fees_sol=parsed,
                                source=url.split("?")[0].split("/")[-1],
                            )
                            return parsed
        except Exception as exc:
            logger.debug("fees.birdeye_error", mint=mint, error=str(exc)[:160])
            continue
    return None



DEXSCREENER_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{mint}"


@dataclass
class VolumeSnapshot:
    mint: str
    pair_address: str | None
    dex_id: str | None
    price_usd: float | None
    liquidity_usd: float | None
    volume_m5_usd: float
    volume_h1_usd: float | None
    txns_m5_buys: int | None
    txns_m5_sells: int | None
    fetched_at: datetime
    name: str | None = None
    symbol: str | None = None
    fees_sol: float | None = None


class DexScreenerClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=12.0)

    async def close(self) -> None:
        await self._http.aclose()

    async def fetch_volume(self, mint: str) -> VolumeSnapshot | None:
        url = DEXSCREENER_TOKEN_URL.format(mint=mint)
        try:
            resp = await self._http.get(url)
            if resp.status_code != 200:
                logger.debug("dexscreener.http_error", status=resp.status_code, mint=mint)
                return None
            data = resp.json()
        except Exception as exc:
            logger.warning("dexscreener.fetch_failed", mint=mint, error=str(exc))
            return None

        pairs: list[dict[str, Any]] = data.get("pairs") or []
        if not pairs:
            return None

        # Pump-only: never use Meteora/Raydium/etc as the volume pair
        sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
        if not sol_pairs:
            sol_pairs = pairs

        pump_pairs = [p for p in sol_pairs if _dex_allowed(p.get("dexId"))]
        if not pump_pairs:
            logger.info(
                "dexscreener.no_pump_pair",
                mint=mint,
                seen=[str(p.get("dexId")) for p in sol_pairs[:8]],
            )
            return None

        def liq(p: dict[str, Any]) -> float:
            return float((p.get("liquidity") or {}).get("usd") or 0)

        best = max(pump_pairs, key=liq)
        vol = best.get("volume") or {}
        txns = best.get("txns") or {}
        m5_tx = txns.get("m5") or {}

        base = best.get("baseToken") or {}
        return VolumeSnapshot(
            mint=mint,
            pair_address=best.get("pairAddress"),
            dex_id=best.get("dexId"),
            price_usd=_f(best.get("priceUsd")),
            liquidity_usd=_f((best.get("liquidity") or {}).get("usd")),
            volume_m5_usd=float(vol.get("m5") or 0),
            volume_h1_usd=_f(vol.get("h1")),
            txns_m5_buys=_i(m5_tx.get("buys")),
            txns_m5_sells=_i(m5_tx.get("sells")),
            fetched_at=datetime.now(timezone.utc),
            name=base.get("name"),
            symbol=base.get("symbol"),
        )


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None



class VolumeMonitor:
    """Poll DexScreener after migration until threshold hit or timeout."""

    def _passes_pump_quality(
        self, mint: str, snap: VolumeSnapshot, fees_sol: float | None
    ) -> tuple[bool, str]:
        """Pump-only + HARD min global fees via canonical qualify(). Fail-closed.

        global_fees = pump.fun cumulative total_fees (SOL) from public coin API.
        Missing / NaN / negative / < MIN ? reject. Never default unknown to 0-accept.
        """
        min_fees = float(getattr(settings, "min_fees_sol", 5.0) or 5.0)
        # Fail closed: only mark verified when we have a finite non-negative number
        # from the authoritative pump.fun fee fetch. Missing ? REJECT.
        # Only true after qualify pass ? missing fees never emit
        # Fail-closed: verified only when we have a finite non-negative fee reading.
        fees_verified = (
            fees_sol is not None
            and fees_sol == fees_sol  # not NaN
            and fees_sol >= 0
        )
        result = qualify_fresh_pump_migration(
            mint=mint,
            dex_id=snap.dex_id,
            global_fees_paid_sol=fees_sol,
            global_fees_verified=True if fees_verified else None,
            min_fees_sol=min_fees,
            require_pump_mint_suffix=bool(
                getattr(settings, "require_pump_mint_suffix", True)
            ),
            allowed_dex_ids=_allowed_dexes(),
            denied_dex_ids=_denied_dexes(),
        )
        if result.accepted:
            return True, "ok"
        reason = result.reason
        if reason == "LOW_GLOBAL_FEES" and result.global_fees_paid_sol is not None:
            reason = f"LOW_GLOBAL_FEES:{result.global_fees_paid_sol:.4f}<{result.required}"
        return False, reason

    async def _record_filter_eval(
        self,
        *,
        mint: str,
        accepted: bool,
        reason: str | None,
        fees_sol: float | None,
        fees_verified: bool,
        snap: "VolumeSnapshot | None" = None,
    ) -> None:
        """Persist one quality decision for operator audit (fail-soft)."""
        try:
            async with self._sessions() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO filter_evaluations (
                            mint, filter_version, accepted, protocol,
                            global_fees_sol, global_fees_source, global_fees_verified,
                            liquidity_usd, volume_usd, rejection_reason,
                            failed_filters, passed_filters, provenance
                        ) VALUES (
                            :mint, :ver, :accepted, :protocol,
                            :fees, :fees_src, :fees_ver,
                            :liq, :vol, :reason,
                            CAST(:failed AS jsonb), CAST(:passed AS jsonb), CAST(:prov AS jsonb)
                        )
                        """
                    ),
                    {
                        "mint": mint,
                        "ver": "axiom-parity-v1.0.0-fees5",
                        "accepted": bool(accepted),
                        "protocol": (snap.dex_id if snap else None),
                        "fees": fees_sol,
                        "fees_src": "birdeye_global_fees_paid",
                        "fees_ver": bool(fees_verified),
                        "liq": (snap.liquidity_usd if snap else None),
                        "vol": (snap.volume_m5_usd if snap else None),
                        "reason": None if accepted else (reason or "REJECTED"),
                        "failed": "[]" if accepted else f'[{{"reason": "{(reason or "REJECTED").replace(chr(34), "")}"}}]',
                        "passed": "[]" if not accepted else '[{"name":"quality"}]',
                        "prov": f'{{"source":"volume._passes_pump_quality","threshold_usd":{float(self._threshold)}}}',
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.warning(
                "filter_eval.persist_failed",
                mint=mint,
                error=f"{type(exc).__name__}: {exc}"[:200],
            )



    async def _persist_market_snapshot(self, mint: str, snap: "VolumeSnapshot") -> None:
        """Write measured DexScreener snapshot so Trending / CC / Backtest have data."""
        if not self._sessions:
            return
        try:
            async with self._sessions() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO market_snapshots (
                            mint, captured_at, price_usd, liquidity_usd,
                            volume_m5_usd, volume_h1_usd, volume_h24_usd,
                            fdv_usd, market_cap_usd, pair_address, dex_id, source
                        ) VALUES (
                            :mint, now(), :price, :liq, :m5, :h1, :h24,
                            :fdv, :mc, :pair, :dex, 'dexscreener'
                        )
                        """
                    ),
                    {
                        "mint": mint,
                        "price": snap.price_usd,
                        "liq": snap.liquidity_usd,
                        "m5": snap.volume_m5_usd,
                        "h1": getattr(snap, "volume_h1_usd", None),
                        "h24": getattr(snap, "volume_h24_usd", None),
                        "fdv": getattr(snap, "fdv_usd", None),
                        "mc": getattr(snap, "market_cap_usd", None),
                        "pair": snap.pair_address,
                        "dex": snap.dex_id,
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.warning("volume.snapshot_persist_failed", mint=mint, error=str(exc)[:200])


    def __init__(
        self,
        publisher: LaunchPublisher,
        *,
        threshold_usd: float | None = None,
        poll_interval_sec: float | None = None,
        max_watch_sec: float | None = None,
    ) -> None:
        self._publisher = publisher
        self._client = DexScreenerClient()
        self._threshold = threshold_usd if threshold_usd is not None else settings.volume_threshold_usd
        self._interval = poll_interval_sec if poll_interval_sec is not None else settings.volume_poll_interval_sec
        self._max_watch = max_watch_sec if max_watch_sec is not None else settings.volume_max_watch_sec
        self._active: set[str] = set()
        self._engine = create_async_engine(
            settings.database_url, pool_pre_ping=True, pool_size=3
        )
        self._sessions = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def close(self) -> None:
        await self._client.close()
        await self._engine.dispose()

    async def _load_smart_money(self, mint: str) -> SmartMoneySignals:
        """Read early buyers + performance for this mint (collector tables)."""
        signals = SmartMoneySignals()
        try:
            async with self._sessions() as session:
                buyers = (
                    await session.execute(
                        text(
                            """
                            SELECT wallet, rank, sol_spent
                            FROM migration_buyers
                            WHERE mint = :mint
                            ORDER BY rank ASC
                            LIMIT 20
                            """
                        ),
                        {"mint": mint},
                    )
                ).mappings().all()
                if not buyers:
                    return signals
                signals.early_buyer_count = len(buyers)
                # Meaningful = known SOL spend above dust (pool already filtered upstream)
                signals.meaningful_buyer_count = sum(
                    1
                    for b in buyers
                    if b.get("sol_spent") is not None
                    and float(b["sol_spent"]) >= 0.05
                )
                wallets = [b["wallet"] for b in buyers]
                perf_rows = (
                    await session.execute(
                        text(
                            """
                            SELECT wallet, early_buy_count, hit_rate, avg_return_pct,
                                   tokens_purchased, realized_pnl_usd,
                                   early_success_rate, early_on_runner, early_on_mega,
                                   early_success_sample
                            FROM wallet_performance
                            WHERE wallet = ANY(:wallets)
                              AND (early_buy_count > 0 OR total_buys > 0
                                   OR COALESCE(early_success_sample, 0) > 0)
                            """
                        ),
                        {"wallets": wallets},
                    )
                ).mappings().all()
                perf_by_w = {r["wallet"]: r for r in perf_rows}
                hit_rates: list[float] = []
                returns: list[float] = []
                success_rates: list[float] = []
                top: list[dict[str, Any]] = []
                for b in buyers:
                    w = b["wallet"]
                    p = perf_by_w.get(w)
                    if not p:
                        continue
                    # "Smart" = has at least one prior early buy and non-trivial history
                    early = int(p.get("early_buy_count") or 0)
                    tokens = int(p.get("tokens_purchased") or 0)
                    if early >= 1 and tokens >= 1:
                        signals.smart_wallet_count += 1
                        hr = p.get("hit_rate")
                        if hr is not None:
                            hit_rates.append(float(hr))
                        ar = p.get("avg_return_pct")
                        if ar is not None:
                            returns.append(float(ar))
                        top.append(
                            {
                                "wallet": w,
                                "rank": b.get("rank"),
                                "hit_rate": float(hr) if hr is not None else None,
                                "avg_return_pct": float(ar) if ar is not None else None,
                                "early_buy_count": early,
                                "early_success_rate": (
                                    float(p["early_success_rate"])
                                    if p.get("early_success_rate") is not None
                                    else None
                                ),
                            }
                        )
                    # Success learning attribution
                    sample = int(p.get("early_success_sample") or 0)
                    if sample >= 2:
                        signals.success_wallet_count += 1
                        sr = p.get("early_success_rate")
                        if sr is not None:
                            success_rates.append(float(sr))
                    if int(p.get("early_on_mega") or 0) >= 1:
                        signals.mega_hunter_count += 1
                if hit_rates:
                    signals.avg_hit_rate = sum(hit_rates) / len(hit_rates)
                if returns:
                    signals.avg_return_pct = sum(returns) / len(returns)
                if success_rates:
                    signals.avg_early_success_rate = sum(success_rates) / len(success_rates)
                signals.top_wallets = top[:5]
        except Exception as exc:
            logger.debug("smart_money.lookup_failed", mint=mint, error=str(exc))
        return signals

    async def _load_entity(self, creator: str | None) -> EntitySignals:
        """Lookup operator entity for migration creator/deployer."""
        signals = EntitySignals()
        if not creator:
            return signals
        try:
            async with self._sessions() as session:
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT e.entity_id, e.entity_type, e.launch_count,
                                   e.wallet_count, e.early_buy_count, e.confidence
                            FROM entity_wallets ew
                            JOIN entities e ON e.entity_id = ew.entity_id
                            WHERE ew.wallet = :w
                            """
                        ),
                        {"w": creator},
                    )
                ).mappings().first()
                if row:
                    signals.entity_id = str(row["entity_id"])
                    signals.entity_type = row.get("entity_type")
                    signals.launch_count = int(row.get("launch_count") or 0)
                    signals.wallet_count = int(row.get("wallet_count") or 1)
                    signals.early_buy_count = int(row.get("early_buy_count") or 0)
                    conf = row.get("confidence")
                    signals.confidence = float(conf) if conf is not None else None
        except Exception as exc:
            logger.debug("entity.lookup_failed", creator=creator, error=str(exc))
        return signals

    def watch(self, migration: DetectedMigration) -> None:
        """Fire-and-forget background watch for this mint."""
        if migration.mint in self._active:
            return
        self._active.add(migration.mint)
        asyncio.create_task(self._run_watch(migration), name=f"vol-{migration.mint[:8]}")

    async def _run_watch(self, migration: DetectedMigration) -> None:
        mint = migration.mint
        started = datetime.now(timezone.utc)
        logger.info(
            "volume.watch_start",
            mint=mint,
            pool=migration.pool,
            threshold_usd=self._threshold,
            max_watch_sec=self._max_watch,
        )
        try:
            elapsed = 0.0
            while elapsed < self._max_watch:
                snap = await self._client.fetch_volume(mint)
                if snap:
                    # fees for quality gate (best effort)
                    fees_sol = await fetch_pump_fees_sol(self._client._http, mint)
                    snap.fees_sol = fees_sol
                    ok, reason = self._passes_pump_quality(mint, snap, fees_sol)
                    fees_verified = (
                        fees_sol is not None
                        and fees_sol == fees_sol
                        and fees_sol >= 0
                    )
                    # Record every structural decision once per snapshot cycle
                    await self._record_filter_eval(
                        mint=mint,
                        accepted=bool(ok),
                        reason=reason,
                        fees_sol=fees_sol,
                        fees_verified=fees_verified,
                        snap=snap,
                    )
                    await self._persist_market_snapshot(mint, snap)
                    logger.info(
                        "volume.snapshot",
                        mint=mint,
                        volume_m5_usd=round(snap.volume_m5_usd, 2),
                        liquidity_usd=snap.liquidity_usd,
                        dex_id=snap.dex_id,
                        pair=snap.pair_address,
                        buys_m5=snap.txns_m5_buys,
                        sells_m5=snap.txns_m5_sells,
                        fees_sol=fees_sol,
                        quality_ok=ok,
                        quality_reason=reason,
                    )
                    if not ok:
                        logger.info(
                            "volume.pump_quality_blocked",
                            mint=mint,
                            reason=reason,
                            dex_id=snap.dex_id,
                            fees_sol=fees_sol,
                            required_min_fees_sol=float(
                                getattr(settings, "min_fees_sol", 5.0) or 5.0
                            ),
                        )
                        # Permanent reject for structural failures.
                        # Fees unknown/low: keep watching ? fees can accumulate.
                        if reason.startswith("DEX_BLOCKED") or reason == "NOT_PUMP_MINT":
                            return
                    elif snap.volume_m5_usd >= self._threshold:
                        await self._emit_pass(migration, snap)
                        return
                await asyncio.sleep(self._interval)
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()

            logger.info(
                "volume.watch_timeout",
                mint=mint,
                threshold_usd=self._threshold,
                watched_sec=round(elapsed, 1),
            )
        except Exception as exc:
            logger.error("volume.watch_failed", mint=mint, error=str(exc))
        finally:
            self._active.discard(mint)

    async def _emit_pass(self, migration: DetectedMigration, snap: VolumeSnapshot) -> None:
        # Re-verify HARD fees gate at emit time (fail-closed). Never trust a stale snap.
        fees_sol = snap.fees_sol
        if fees_sol is None:
            fees_sol = await fetch_pump_fees_sol(self._client._http, migration.mint)
            snap.fees_sol = fees_sol
        ok, reason = self._passes_pump_quality(migration.mint, snap, fees_sol)
        fees_verified = fees_sol is not None and fees_sol == fees_sol and fees_sol >= 0
        await self._record_filter_eval(
            mint=migration.mint,
            accepted=bool(ok),
            reason=reason,
            fees_sol=fees_sol,
            fees_verified=fees_verified,
            snap=snap,
        )
        if not ok:
            logger.info(
                "volume.emit_blocked_fees_gate",
                mint=migration.mint,
                reason=reason,
                fees_sol=fees_sol,
                required_min_fees_sol=float(getattr(settings, "min_fees_sol", 5.0) or 5.0),
            )
            return

        fees_verified = fees_sol is not None
        logger.info(
            "volume.threshold_hit",
            mint=migration.mint,
            volume_m5_usd=round(snap.volume_m5_usd, 2),
            threshold_usd=self._threshold,
            pool=migration.pool,
            pair=snap.pair_address,
            fees_sol=fees_sol,
            global_fees_verified=fees_verified,
        )

        # Smart-money + entity context (collector + entity-resolver)
        smart = await self._load_smart_money(migration.mint)
        entity = await self._load_entity(migration.creator)
        result = score_alert_candidate(
            volume_m5_usd=snap.volume_m5_usd,
            threshold_usd=self._threshold,
            liquidity_usd=snap.liquidity_usd,
            smart=smart,
            entity=entity,
        )
        logger.info(
            "alert.stinky_score",
            mint=migration.mint,
            score=result.score,
            confidence=result.confidence,
            model=result.model_version,
            smart_wallets=smart.smart_wallet_count,
            early_buyers=smart.early_buyer_count,
            entity_launches=entity.launch_count,
            entity_id=entity.entity_id,
            explanation=result.explanation,
        )

        
        # Persist score snapshot for Time Machine (wallet + mint)
        try:
            async with self._sessions() as session:
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
                import json as _json
                expl = _json.dumps(result.explanation) if result.explanation else None
                sig = _json.dumps(
                    {
                        "early_buyer_count": smart.early_buyer_count,
                        "meaningful_buyer_count": smart.meaningful_buyer_count,
                        "smart_wallet_count": smart.smart_wallet_count,
                        "success_wallet_count": smart.success_wallet_count,
                        "avg_early_success_rate": smart.avg_early_success_rate,
                        "mega_hunter_count": smart.mega_hunter_count,
                        "entity_launch_count": entity.launch_count,
                    }
                )
                if migration.creator:
                    await session.execute(
                        text(
                            """
                            INSERT INTO score_snapshots (
                                subject_type, subject_id, score, confidence,
                                model_version, context, mint, explanation, signals
                            ) VALUES (
                                'wallet', :sid, :score, :conf,
                                :model, 'alert_candidate', :mint,
                                CAST(:expl AS jsonb), CAST(:sig AS jsonb)
                            )
                            """
                        ),
                        {
                            "sid": migration.creator,
                            "score": float(result.score),
                            "conf": float(result.confidence) if result.confidence is not None else None,
                            "model": result.model_version,
                            "mint": migration.mint,
                            "expl": expl,
                            "sig": sig,
                        },
                    )
                await session.execute(
                    text(
                        """
                        INSERT INTO score_snapshots (
                            subject_type, subject_id, score, confidence,
                            model_version, context, mint, explanation, signals
                        ) VALUES (
                            'mint', :sid, :score, :conf,
                            :model, 'alert_candidate', :mint,
                            CAST(:expl AS jsonb), CAST(:sig AS jsonb)
                        )
                        """
                    ),
                    {
                        "sid": migration.mint,
                        "score": float(result.score),
                        "conf": float(result.confidence) if result.confidence is not None else None,
                        "model": result.model_version,
                        "mint": migration.mint,
                        "expl": expl,
                        "sig": sig,
                    },
                )
                await session.commit()
                logger.info(
                    "score.snapshot_saved",
                    mint=migration.mint,
                    creator=migration.creator,
                    score=result.score,
                )
        except Exception as exc:
            logger.warning("score.snapshot_failed", error=str(exc), mint=migration.mint)


        # Persist threshold event
        vol_event = Event(
            event_type=EventType.VOLUME_THRESHOLD,
            signature=migration.signature,
            block_time=datetime.now(timezone.utc),
            payload={
                "mint": migration.mint,
                "pool": migration.pool,
                "pair_address": snap.pair_address,
                "volume_m5_usd": snap.volume_m5_usd,
                "liquidity_usd": snap.liquidity_usd,
                "price_usd": snap.price_usd,
                "dex_id": snap.dex_id,
                "threshold_usd": self._threshold,
                "creator": migration.creator,
                "name": snap.name,
                "symbol": snap.symbol,
                "fees_sol": fees_sol,
                "global_fees_paid_sol": fees_sol,
                "global_fees_verified": fees_verified,
                "global_fees_source": "birdeye_global_fees_paid",
            },
            producer="sentinel-volume",
        )
        await self._publisher.publish_raw_event(vol_event, kind="volume")

        # Alert candidate ? Discord consumes this
        # fees_sol MUST be present so downstream hard gate can fail-closed.
        alert_event = Event(
            event_type=EventType.ALERT_CANDIDATE,
            signature=migration.signature,
            block_time=datetime.now(timezone.utc),
            payload={
                "mint": migration.mint,
                "pool": migration.pool,
                "pair_address": snap.pair_address,
                "reason": "migration_plus_volume",
                "volume_m5_usd": snap.volume_m5_usd,
                "liquidity_usd": snap.liquidity_usd,
                "price_usd": snap.price_usd,
                "threshold_usd": self._threshold,
                "creator": migration.creator,
                "destination": migration.destination,
                "name": snap.name,
                "symbol": snap.symbol,
                "dex_id": snap.dex_id,
                "fees_sol": fees_sol,
                "global_fees_paid_sol": fees_sol,
                "global_fees_verified": fees_verified,
                "global_fees_source": "birdeye_global_fees_paid",
                "global_fees_calculation_version": "v1_pump_total_fees",
                "stinky_score": result.score,
                "confidence": result.confidence,
                "score_model": result.model_version,
                "score_explanation": result.explanation,
                "early_buyer_count": smart.early_buyer_count,
                "meaningful_buyer_count": smart.meaningful_buyer_count,
                "smart_wallet_count": smart.smart_wallet_count,
                "smart_avg_hit_rate": smart.avg_hit_rate,
                "smart_avg_return_pct": smart.avg_return_pct,
                "smart_top_wallets": smart.top_wallets,
                "success_wallet_count": getattr(smart, "success_wallet_count", 0),
                "avg_early_success_rate": getattr(smart, "avg_early_success_rate", None),
                "mega_hunter_count": getattr(smart, "mega_hunter_count", 0),
                "entity_id": entity.entity_id,
                "entity_launch_count": entity.launch_count,
                "entity_wallet_count": entity.wallet_count,
                "entity_confidence": entity.confidence,
            },
            producer="sentinel-volume",
        )
        await self._publisher.publish_raw_event(alert_event, kind="alert")
