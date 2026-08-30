"""Volume watch + Gate 1 investigation funnel.

Early snapshots persist at the observation threshold.
Gate 1 ($150k 5m, configurable to $200k) starts deep inspection.
ALERT_CANDIDATE is emitted only after inspection + intelligence, never on volume alone.
FeeResolver is optional evidence after Gate 1 — unknown fees do not reject.
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
from sentinel.score import EntitySignals, SmartMoneySignals

try:
    from stinky_core.admission import FILTER_VERSION, GATE1_VOLUME_5M_USD, clamp_gate1_volume
    from stinky_core.fees import (
        FEE_OBSERVATIONS_DDL,
        FEE_OBSERVATIONS_INDEXES,
        FEE_OBSERVATIONS_INSERT,
        RESOLVER_VERSION,
        FeeObservation,
        FeeResolver,
        unknown_observation,
    )
    from stinky_core.intelligence import (
        INTEL_VERSION,
        MARKET_INSPECTIONS_DDL,
        MARKET_INSPECTIONS_INDEXES,
        MARKET_INSPECTIONS_INSERT,
        can_alert_investigation,
        inspection_persist_params,
        investigate,
    )
except ImportError:  # pragma: no cover
    import sys
    from pathlib import Path

    _CORE = Path(__file__).resolve().parents[4] / "packages" / "stinky-core" / "src"
    if str(_CORE) not in sys.path:
        sys.path.insert(0, str(_CORE))
    from stinky_core.admission import FILTER_VERSION, GATE1_VOLUME_5M_USD, clamp_gate1_volume
    from stinky_core.fees import (
        FEE_OBSERVATIONS_DDL,
        FEE_OBSERVATIONS_INDEXES,
        FEE_OBSERVATIONS_INSERT,
        RESOLVER_VERSION,
        FeeObservation,
        FeeResolver,
        unknown_observation,
    )
    from stinky_core.intelligence import (
        INTEL_VERSION,
        MARKET_INSPECTIONS_DDL,
        MARKET_INSPECTIONS_INDEXES,
        MARKET_INSPECTIONS_INSERT,
        can_alert_investigation,
        inspection_persist_params,
        investigate,
    )

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


def _fee_rpc_urls() -> tuple[str, ...]:
    urls: list[str] = []
    for u in (
        getattr(settings, "public_rpc_url", None),
        "https://solana-rpc.publicnode.com",
        getattr(settings, "solana_rpc_url", None),
    ):
        if not u:
            continue
        s = str(u).strip()
        if not s or "helius" in s.lower():
            continue
        if s not in urls:
            urls.append(s)
    return tuple(urls) or ("https://solana-rpc.publicnode.com",)


def _new_fee_resolver() -> FeeResolver:
    return FeeResolver(rpc_urls=_fee_rpc_urls(), max_txs=80)


async def resolve_global_fees(
    mint: str,
    *,
    protocol: str | None = None,
    pool: str | None = None,
) -> FeeObservation:
    """Authoritative fees only. Never fabricates. Unknown stays unknown."""
    mint_s = (mint or "").strip()
    if not mint_s:
        return unknown_observation("", error="INVALID_MINT")

    def _sync() -> FeeObservation:
        return _new_fee_resolver().resolve(mint_s, protocol=protocol, pool=pool)

    return await asyncio.to_thread(_sync)


async def fetch_pump_fees_sol(client: httpx.AsyncClient, mint: str) -> float | None:
    """Verified global fees only. Unknown / unverified → None. Never a guess.

    `client` is unused; kept so existing call sites stay compatible.
    """
    _ = client
    obs = await resolve_global_fees(mint, protocol="pumpswap")
    return obs.global_fees_sol if obs.fees_verified else None


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

    def _gate1_volume(self) -> float:
        raw = getattr(settings, "gate1_volume_5m_usd", None)
        if raw is None:
            raw = getattr(settings, "min_volume_usd", GATE1_VOLUME_5M_USD)
        return clamp_gate1_volume(raw)

    def _passes_pump_quality(
        self,
        mint: str,
        snap: VolumeSnapshot,
        fees_sol: float | None,
        *,
        fees_verified: bool | None = None,
    ) -> tuple[bool, str]:
        """Gate 1: mint + DEX + 5m volume. Fees are optional evidence, not a reject."""
        min_fees = float(getattr(settings, "min_fees_sol", 1.0) or 1.0)
        verified = True if fees_verified is True else (False if fees_verified is False else None)
        result = qualify_fresh_pump_migration(
            mint=mint,
            dex_id=snap.dex_id,
            volume_m5_usd=snap.volume_m5_usd,
            global_fees_paid_sol=fees_sol if verified is True else None,
            global_fees_verified=verified,
            min_fees_sol=min_fees,
            min_volume_usd=self._gate1_volume(),
            require_pump_mint_suffix=bool(
                getattr(settings, "require_pump_mint_suffix", True)
            ),
            allowed_dex_ids=_allowed_dexes(),
            denied_dex_ids=_denied_dexes(),
        )
        if result.accepted:
            return True, "ok"
        return False, result.reason

    async def _record_filter_eval(
        self,
        *,
        mint: str,
        accepted: bool,
        reason: str | None,
        fees_sol: float | None,
        fees_verified: bool,
        snap: "VolumeSnapshot | None" = None,
        fees_source: str | None = None,
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
                        "ver": FILTER_VERSION,
                        "accepted": bool(accepted),
                        "protocol": (snap.dex_id if snap else None),
                        "fees": fees_sol if fees_verified else None,
                        "fees_src": fees_source or RESOLVER_VERSION,
                        "fees_ver": bool(fees_verified),
                        "liq": (snap.liquidity_usd if snap else None),
                        "vol": (snap.volume_m5_usd if snap else None),
                        "reason": None if accepted else (reason or "REJECTED"),
                        "failed": "[]" if accepted else f'[{{"reason": "{(reason or "REJECTED").replace(chr(34), "")}"}}]',
                        "passed": "[]" if not accepted else '[{"name":"quality"}]',
                        "prov": (
                            f'{{"source":"volume._passes_pump_quality",'
                            f'"threshold_usd":{float(self._threshold)},'
                            f'"resolver_version":"{RESOLVER_VERSION}"}}'
                        ),
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.warning(
                "filter_eval.persist_failed",
                mint=mint,
                error=f"{type(exc).__name__}: {exc}"[:200],
            )

    async def _persist_fee_observation(self, obs: FeeObservation) -> None:
        """Append-only fee observation. Never overwrite history."""
        try:
            async with self._sessions() as session:
                await session.execute(text(FEE_OBSERVATIONS_DDL))
                for idx in FEE_OBSERVATIONS_INDEXES:
                    await session.execute(text(idx))
                await session.execute(text(FEE_OBSERVATIONS_INSERT), obs.persist_params())
                await session.commit()
        except Exception as exc:
            logger.warning(
                "fee_observation.persist_failed",
                mint=obs.mint,
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
        try:
            from stinky_core.memory import IntelligenceMemory
            self._memory = IntelligenceMemory()
        except Exception:
            self._memory = None
        self._memory_hydrated = False

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
            observation_threshold_usd=self._threshold,
            gate1_volume_usd=self._gate1_volume(),
            max_watch_sec=self._max_watch,
        )
        try:
            elapsed = 0.0
            while elapsed < self._max_watch:
                snap = await self._client.fetch_volume(mint)
                if snap:
                    if snap.dex_id and not _dex_allowed(snap.dex_id):
                        await self._persist_market_snapshot(mint, snap)
                        await self._record_filter_eval(
                            mint=mint,
                            accepted=False,
                            reason="PROTOCOL_DISABLED",
                            fees_sol=None,
                            fees_verified=False,
                            snap=snap,
                            fees_source="skipped.denied_protocol",
                        )
                        logger.info(
                            "volume.pump_quality_blocked",
                            mint=mint,
                            reason="PROTOCOL_DISABLED",
                            dex_id=snap.dex_id,
                        )
                        return

                    await self._persist_market_snapshot(mint, snap)
                    # Gate 1 BEFORE expensive fee resolve.
                    ok, reason = self._passes_pump_quality(
                        mint, snap, None, fees_verified=None
                    )
                    await self._record_filter_eval(
                        mint=mint,
                        accepted=bool(ok),
                        reason=reason,
                        fees_sol=None,
                        fees_verified=False,
                        snap=snap,
                        fees_source="gate1.pre_fee",
                    )
                    logger.info(
                        "volume.snapshot",
                        mint=mint,
                        volume_m5_usd=round(snap.volume_m5_usd, 2),
                        liquidity_usd=snap.liquidity_usd,
                        dex_id=snap.dex_id,
                        pair=snap.pair_address,
                        buys_m5=snap.txns_m5_buys,
                        sells_m5=snap.txns_m5_sells,
                        gate1_ok=ok,
                        gate1_reason=reason,
                    )
                    if not ok:
                        if reason in (
                            "PROTOCOL_DISABLED",
                            "PROTOCOL_UNKNOWN",
                            "INVALID_MINT",
                            "INVALID_MARKET_DATA",
                            "NOT_PUMP_MINT",
                        ):
                            return
                        # VOLUME_BELOW_MIN / VOLUME_UNKNOWN: keep watching
                    else:
                        alerted = await self._investigate_and_maybe_alert(migration, snap)
                        if alerted:
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

    async def _persist_inspection(self, params: dict[str, Any]) -> None:
        try:
            async with self._sessions() as session:
                await session.execute(text(MARKET_INSPECTIONS_DDL))
                for idx in MARKET_INSPECTIONS_INDEXES:
                    await session.execute(text(idx))
                await session.execute(text(MARKET_INSPECTIONS_INSERT), params)
                await session.commit()
        except Exception as exc:
            logger.warning(
                "inspection.persist_failed",
                mint=params.get("mint"),
                error=f"{type(exc).__name__}: {exc}"[:200],
            )

    async def _hydrate_memory(self) -> None:
        """Load as-of observations from Postgres. Fail-soft. Never fabricates."""
        if self._memory is None or self._memory_hydrated:
            return
        try:
            from stinky_core.memory import (
                MEMORY_SELECT_CREATOR_OBS,
                MEMORY_SELECT_CREATOR_OUTCOME,
                MEMORY_SELECT_FINGERPRINT,
                MEMORY_SELECT_FINGERPRINT_OUTCOME,
                MEMORY_SELECT_WALLET_OBS,
                MEMORY_SELECT_WALLET_OUTCOME,
            )
            async with self._sessions() as session:
                wobs = (await session.execute(text(MEMORY_SELECT_WALLET_OBS))).mappings().all()
                wout = (await session.execute(text(MEMORY_SELECT_WALLET_OUTCOME))).mappings().all()
                cobs = (await session.execute(text(MEMORY_SELECT_CREATOR_OBS))).mappings().all()
                cout = (await session.execute(text(MEMORY_SELECT_CREATOR_OUTCOME))).mappings().all()
                fps = (await session.execute(text(MEMORY_SELECT_FINGERPRINT))).mappings().all()
                fpout = (await session.execute(text(MEMORY_SELECT_FINGERPRINT_OUTCOME))).mappings().all()
            self._memory.hydrate({
                "wallet_obs": [dict(r) for r in wobs],
                "wallet_outcomes": [dict(r) for r in wout],
                "creator_obs": [dict(r) for r in cobs],
                "creator_outcomes": [dict(r) for r in cout],
                "fingerprints": [dict(r) for r in fps],
                "fingerprint_outcomes": [dict(r) for r in fpout],
            })
            logger.info("memory.hydrated", **self._memory.to_stats())
        except Exception as exc:
            logger.warning("memory.hydrate_failed", error=str(exc)[:200])
        self._memory_hydrated = True

    async def _persist_memory_decision(
        self,
        *,
        mint: str,
        observed_at: Any,
        buyers: list[dict[str, Any]] | None,
        creator: str | None,
        fingerprint: str | None,
    ) -> None:
        try:
            from stinky_core.memory import (
                MEMORY_INSERT_CREATOR_OBS,
                MEMORY_INSERT_FINGERPRINT,
                MEMORY_INSERT_WALLET_OBS,
            )
            import json
            async with self._sessions() as session:
                for b in buyers or []:
                    w = str(b.get("wallet") or b.get("userAddress") or "").strip()
                    if not w:
                        continue
                    spent = b.get("sol_spent") if b.get("sol_spent") is not None else b.get("amountSol")
                    try:
                        spent_f = float(spent) if spent is not None else None
                    except (TypeError, ValueError):
                        spent_f = None
                    await session.execute(
                        text(MEMORY_INSERT_WALLET_OBS),
                        {
                            "wallet": w,
                            "mint": mint,
                            "observed_at": observed_at,
                            "role": "early_buyer",
                            "sol_spent": spent_f,
                            "source": "observed",
                        },
                    )
                if creator:
                    await session.execute(
                        text(MEMORY_INSERT_CREATOR_OBS),
                        {
                            "creator": creator,
                            "mint": mint,
                            "observed_at": observed_at,
                            "migrated": True,
                            "source": "observed",
                        },
                    )
                if fingerprint:
                    await session.execute(
                        text(MEMORY_INSERT_FINGERPRINT),
                        {
                            "fingerprint": fingerprint,
                            "mint": mint,
                            "observed_at": observed_at,
                            "features": json.dumps({}),
                        },
                    )
                await session.commit()
        except Exception as exc:
            logger.warning("memory.persist_failed", mint=mint, error=str(exc)[:200])

    async def _investigate_and_maybe_alert(
        self, migration: DetectedMigration, snap: VolumeSnapshot
    ) -> bool:
        """Deep inspect after Gate 1. Returns True if an ALERT_CANDIDATE was emitted."""
        mint = migration.mint
        await self._hydrate_memory()
        obs = await resolve_global_fees(
            mint, protocol=snap.dex_id, pool=snap.pair_address
        )
        await self._persist_fee_observation(obs)
        fees_sol = obs.global_fees_sol if obs.fees_verified else None
        snap.fees_sol = fees_sol
        fee_status = "VERIFIED" if obs.fees_verified else "UNKNOWN"

        smart = await self._load_smart_money(mint)
        entity = await self._load_entity(migration.creator)
        buyers_rows: list[dict[str, Any]] = []
        perf_map: dict[str, dict[str, Any]] = {}
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
                            LIMIT 40
                            """
                        ),
                        {"mint": mint},
                    )
                ).mappings().all()
                buyers_rows = [dict(b) for b in buyers]
                wallets = [b["wallet"] for b in buyers_rows if b.get("wallet")]
                if wallets:
                    perf_rows = (
                        await session.execute(
                            text(
                                """
                                SELECT wallet, early_buy_count, hit_rate, avg_return_pct,
                                       tokens_purchased
                                FROM wallet_performance
                                WHERE wallet = ANY(:wallets)
                                """
                            ),
                            {"wallets": wallets},
                        )
                    ).mappings().all()
                    perf_map = {r["wallet"]: dict(r) for r in perf_rows}
        except Exception as exc:
            logger.debug("investigation.buyers_lookup_failed", mint=mint, error=str(exc)[:200])

        creator_profile = None
        if entity.entity_id:
            creator_profile = {
                "entity_id": entity.entity_id,
                "launch_count": entity.launch_count,
                "wallet_count": entity.wallet_count,
                "known": True,
            }

        bundle: dict[str, Any] = {
            "mint": mint,
            "volume_m5_usd": snap.volume_m5_usd,
            "volume_usd": snap.volume_m5_usd,
            "liquidity_usd": snap.liquidity_usd,
            "txns_m5_buys": snap.txns_m5_buys,
            "txns_m5_sells": snap.txns_m5_sells,
            "buyers": buyers_rows or None,
            "wallet_performance": perf_map or None,
            "wallets_as_of_decision": True,
            "creator_profile": creator_profile,
            "creator": migration.creator,
            "fee_status": fee_status,
            "global_fees_sol": fees_sol,
            "volume_gate": self._gate1_volume(),
            "decision_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        inv = investigate(bundle, memory=getattr(self, "_memory", None))
        mem = getattr(self, "_memory", None)
        if mem is not None:
            try:
                mem.ingest_decision(
                    mint=mint,
                    observed_at=bundle.get("decision_timestamp"),
                    buyers=buyers_rows,
                    creator=migration.creator,
                    fingerprint=inv.fingerprint,
                )
                await self._persist_memory_decision(
                    mint=mint,
                    observed_at=bundle.get("decision_timestamp"),
                    buyers=buyers_rows,
                    creator=migration.creator,
                    fingerprint=inv.fingerprint,
                )
            except Exception:
                pass
        alert_ok, alert_reason = can_alert_investigation(True, inv)
        if alert_ok:
            inv.pipeline_status = "ALERT"
        await self._persist_inspection(
            inspection_persist_params(inv, alert_ok=alert_ok, alert_reason=alert_reason)
        )

        logger.info(
            "investigation.complete",
            mint=mint,
            pipeline_status=inv.pipeline_status,
            stinky_score=inv.score.score,
            synthetic=inv.synthetic.level,
            rug=inv.rug.level,
            has_intelligence=inv.has_intelligence,
            fee_status=inv.fee_status,
            alert_ok=alert_ok,
            alert_reason=alert_reason,
            model=INTEL_VERSION,
        )

        try:
            from stinky_core.events.base import Event, EventType

            gate1_event = Event(
                event_type=EventType.MARKET_GATE1_PASSED,
                signature=migration.signature,
                block_time=datetime.now(timezone.utc),
                payload={
                    "mint": mint,
                    "volume_m5_usd": snap.volume_m5_usd,
                    "threshold_usd": self._gate1_volume(),
                    "dex_id": snap.dex_id,
                    "filter_version": FILTER_VERSION,
                },
                producer="sentinel-volume",
            )
            await self._publisher.publish_raw_event(gate1_event, kind="gate1")
            insp_event = Event(
                event_type=EventType.MARKET_INSPECTION_COMPLETED,
                signature=migration.signature,
                block_time=datetime.now(timezone.utc),
                payload={
                    "mint": mint,
                    "pipeline_status": inv.pipeline_status,
                    "stinky_score": inv.score.score,
                    "confidence": inv.score.confidence,
                    "synthetic_level": inv.synthetic.level,
                    "rug_level": inv.rug.level,
                    "runner_potential": inv.runner.score,
                    "has_intelligence": inv.has_intelligence,
                    "fee_status": inv.fee_status,
                    "global_fees_sol": inv.global_fees_sol,
                    "alert_ok": alert_ok,
                    "alert_reason": alert_reason,
                    "model_version": INTEL_VERSION,
                },
                producer="sentinel-volume",
            )
            await self._publisher.publish_raw_event(insp_event, kind="inspection")
        except Exception as exc:
            logger.debug("investigation.event_publish_failed", mint=mint, error=str(exc)[:200])

        if not alert_ok:
            logger.info(
                "volume.gate1_not_alert",
                mint=mint,
                reason=alert_reason,
                score=inv.score.score,
                has_intelligence=inv.has_intelligence,
            )
            return False

        # Reuse existing scoring snapshot + ALERT_CANDIDATE emit
        await self._emit_alert(migration, snap, obs, inv, smart, entity)
        return True

    async def _emit_alert(
        self,
        migration: DetectedMigration,
        snap: VolumeSnapshot,
        obs: FeeObservation,
        inv: Any,
        smart: SmartMoneySignals,
        entity: EntitySignals,
    ) -> None:
        fees_sol = inv.global_fees_sol
        logger.info(
            "volume.alert_candidate",
            mint=migration.mint,
            volume_m5_usd=round(snap.volume_m5_usd, 2),
            threshold_usd=self._gate1_volume(),
            score=inv.score.score,
            fees_sol=fees_sol,
            fee_status=inv.fee_status,
        )

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
                expl = _json.dumps(inv.score.to_dict())
                sig = _json.dumps(
                    {
                        "early_buyer_count": smart.early_buyer_count,
                        "meaningful_buyer_count": smart.meaningful_buyer_count,
                        "smart_wallet_count": smart.smart_wallet_count,
                        "success_wallet_count": smart.success_wallet_count,
                        "avg_early_success_rate": smart.avg_early_success_rate,
                        "mega_hunter_count": smart.mega_hunter_count,
                        "entity_launch_count": entity.launch_count,
                        "synthetic_level": inv.synthetic.level,
                        "rug_level": inv.rug.level,
                        "runner_potential": inv.runner.score,
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
                            "score": float(inv.score.score),
                            "conf": float(inv.score.confidence),
                            "model": inv.score.model_version,
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
                        "score": float(inv.score.score),
                        "conf": float(inv.score.confidence),
                        "model": inv.score.model_version,
                        "mint": migration.mint,
                        "expl": expl,
                        "sig": sig,
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.warning("score.snapshot_failed", error=str(exc), mint=migration.mint)

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
                "threshold_usd": self._gate1_volume(),
                "creator": migration.creator,
                "name": snap.name,
                "symbol": snap.symbol,
                "fees_sol": fees_sol,
                "global_fees_paid_sol": fees_sol,
                "global_fees_verified": bool(obs.fees_verified),
                "global_fees_source": obs.fees_source,
            },
            producer="sentinel-volume",
        )
        await self._publisher.publish_raw_event(vol_event, kind="volume")

        alert_event = Event(
            event_type=EventType.ALERT_CANDIDATE,
            signature=migration.signature,
            block_time=datetime.now(timezone.utc),
            payload={
                "mint": migration.mint,
                "pool": migration.pool,
                "pair_address": snap.pair_address,
                "reason": "gate1_plus_intelligence",
                "volume_m5_usd": snap.volume_m5_usd,
                "liquidity_usd": snap.liquidity_usd,
                "price_usd": snap.price_usd,
                "threshold_usd": self._gate1_volume(),
                "creator": migration.creator,
                "destination": migration.destination,
                "name": snap.name,
                "symbol": snap.symbol,
                "dex_id": snap.dex_id,
                "fees_sol": fees_sol,
                "global_fees_paid_sol": fees_sol,
                "global_fees_verified": bool(obs.fees_verified),
                "global_fees_source": obs.fees_source,
                "global_fees_calculation_version": RESOLVER_VERSION,
                "stinky_score": inv.score.score,
                "confidence": inv.score.confidence,
                "score_model": inv.score.model_version,
                "score_explanation": inv.score.to_dict(),
                "inspection_complete": True,
                "has_intelligence": inv.has_intelligence,
                "synthetic_level": inv.synthetic.level,
                "rug_level": inv.rug.level,
                "runner_potential": inv.runner.score,
                "pipeline_status": inv.pipeline_status,
                "fee_status": inv.fee_status,
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
