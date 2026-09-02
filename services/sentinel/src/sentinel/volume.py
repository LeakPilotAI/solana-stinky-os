"""Volume watch + Gate 1 investigation funnel.

Early snapshots persist at the observation threshold.
Gate 1 ($150k 5m, configurable to $200k) starts deep inspection.
ALERT_CANDIDATE is emitted only after inspection + intelligence, never on volume alone.
FeeResolver is optional evidence after Gate 1 — unknown fees do not reject.
"""

from __future__ import annotations

import asyncio
import time
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

from stinky_core.observation import watch_should_resume, watch_tick_decision

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
    market_cap_usd: float | None = None


class DexScreenerClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=12.0)
        self.last_probe: dict[str, Any] | None = None
        self._cooldown_until = 0.0

    async def close(self) -> None:
        await self._http.aclose()

    async def fetch_volume(self, mint: str) -> VolumeSnapshot | None:
        url = DEXSCREENER_TOKEN_URL.format(mint=mint)
        now = time.monotonic()
        if now < self._cooldown_until:
            return None
        t0 = time.monotonic()
        try:
            resp = await self._http.get(url)
            ms = round((time.monotonic() - t0) * 1000, 1)
            if resp.status_code == 429:
                self._cooldown_until = time.monotonic() + 60.0
                self.last_probe = {
                    "provider": "dexscreener",
                    "ok": False,
                    "status": "DEGRADED",
                    "http_status": 429,
                    "latency_ms": ms,
                    "error": "rate_limited",
                    "source": "dexscreener",
                    "at": datetime.now(timezone.utc).isoformat(),
                }
                logger.warning("dexscreener.http_429", mint=mint[:12], cooldown_sec=60)
                return None
            if resp.status_code != 200:
                self.last_probe = {
                    "provider": "dexscreener",
                    "ok": False,
                    "status": "DOWN" if resp.status_code >= 500 else "DEGRADED",
                    "http_status": resp.status_code,
                    "latency_ms": ms,
                    "error": f"http_{resp.status_code}",
                    "source": "dexscreener",
                    "at": datetime.now(timezone.utc).isoformat(),
                }
                logger.debug("dexscreener.http_error", status=resp.status_code, mint=mint)
                return None
            data = resp.json()
        except Exception as exc:
            self.last_probe = {
                "provider": "dexscreener",
                "ok": False,
                "status": "DOWN",
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "error": str(exc)[:200],
                "source": "dexscreener",
                "at": datetime.now(timezone.utc).isoformat(),
            }
            logger.warning("dexscreener.fetch_failed", mint=mint, error=str(exc))
            return None

        pairs: list[dict[str, Any]] = data.get("pairs") or []
        if not pairs:
            self.last_probe = {
                "provider": "dexscreener",
                "ok": True,
                "status": "UP",
                "latency_ms": ms,
                "http_status": 200,
                "note": "no_pairs",
                "source": "dexscreener",
                "at": datetime.now(timezone.utc).isoformat(),
            }
            return None

        # Pump-only: never use Meteora/Raydium/etc as the volume pair
        sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
        if not sol_pairs:
            sol_pairs = pairs

        pump_pairs = [p for p in sol_pairs if _dex_allowed(p.get("dexId"))]
        if not pump_pairs:
            self.last_probe = {
                "provider": "dexscreener",
                "ok": True,
                "status": "UP",
                "latency_ms": ms,
                "http_status": 200,
                "note": "no_pump_pair",
                "source": "dexscreener",
                "at": datetime.now(timezone.utc).isoformat(),
            }
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
        self.last_probe = {
            "provider": "dexscreener",
            "ok": True,
            "status": "UP",
            "latency_ms": ms,
            "http_status": 200,
            "source": "dexscreener",
            "at": datetime.now(timezone.utc).isoformat(),
        }
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
            market_cap_usd=_f(best.get("marketCap")),
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
        configured = max_watch_sec if max_watch_sec is not None else settings.volume_max_watch_sec
        try:
            watch = float(configured or 0)
        except (TypeError, ValueError):
            watch = 0.0
        # Observation window includes T+1800. Never stop collecting earlier than that.
        self._max_watch = max(watch, 1800.0)
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

    async def start(self) -> None:
        """Hydrate memory and resume open T+1800 watches. Fail-soft."""
        await self._hydrate_memory()
        await self._resume_open_watches()

    async def _resume_open_watches(self) -> None:
        """After restart: keep observing investigations still inside the window."""
        mem = getattr(self, "_memory", None)
        if mem is None:
            return
        try:
            from stinky_core.memory import _parse_ts
        except Exception:
            return
        now = datetime.now(timezone.utc)
        n = 0
        for rec in list(getattr(mem, "investigations", []) or []):
            mint = str(rec.get("mint") or "").strip()
            if not mint or mint in self._active:
                continue
            t0 = _parse_ts(rec.get("gate1_at") or rec.get("decision_timestamp"))
            if t0 is None:
                continue
            elapsed = (now - t0).total_seconds()
            if not watch_should_resume(elapsed_sec=elapsed, max_watch_sec=self._max_watch):
                continue
            mig = DetectedMigration(
                mint=mint,
                pool=str(rec.get("pair_identifier") or rec.get("pool") or ""),
                creator=rec.get("creator"),
                destination=str(rec.get("protocol") or "pumpswap"),
                source="resume-watch",
                block_time=t0,
            )
            self._active.add(mint)
            asyncio.create_task(
                self._run_watch(mig, started=t0, investigated=True, resumed=True),
                name=f"vol-resume-{mint[:8]}",
            )
            n += 1
            await self._trace(
                mint=mint,
                kind="watch_resumed",
                message="Watch resumed after process restart",
                extra={"elapsed_sec": elapsed, "resumed": True},
            )
        if n:
            logger.info("volume.watches_resumed", n=n, max_watch_sec=self._max_watch)

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

    async def _run_watch(
        self,
        migration: DetectedMigration,
        *,
        started: datetime | None = None,
        investigated: bool = False,
        resumed: bool = False,
    ) -> None:
        mint = migration.mint
        started = started or datetime.now(timezone.utc)
        mem = getattr(self, "_memory", None)
        if mem is not None and any(str(r.get("mint")) == mint for r in getattr(mem, "investigations", []) or []):
            investigated = True
        logger.info(
            "volume.watch_start",
            mint=mint,
            pool=migration.pool,
            observation_threshold_usd=self._threshold,
            gate1_volume_usd=self._gate1_volume(),
            max_watch_sec=self._max_watch,
            resumed=resumed,
            source=migration.source,
        )
        await self._trace(
            mint=mint,
            kind="watch_start" if not resumed else "watch_resumed",
            message="Watch resumed after process restart" if resumed else "Migration watch started",
            extra={"pool": migration.pool, "resumed": resumed, "source": migration.source},
        )
        await self._upsert_watch(
            mint=mint,
            started_at=started.isoformat(),
            status="DETECTED" if not investigated else "WATCHING",
            resumed=resumed,
            pool=migration.pool,
        )
        try:
            while True:
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                if elapsed >= self._max_watch:
                    break
                snap = await self._client.fetch_volume(mint)
                probe = getattr(self._client, "last_probe", None)
                if probe:
                    await self._record_probe(probe)
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
                        await self._upsert_watch(
                            mint=mint, started_at=started.isoformat(), status="FAILED",
                            resumed=resumed, stop_reason="PROTOCOL_DISABLED", pool=migration.pool,
                        )
                        await self._trace(mint=mint, kind="watch_stop", message="Watch stopped PROTOCOL_DISABLED")
                        return

                    await self._persist_market_snapshot(mint, snap)
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
                    action = watch_tick_decision(
                        investigated=investigated, gate_ok=bool(ok), reason=reason
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
                        investigated=investigated,
                        action=action,
                    )
                    if action == "stop":
                        await self._upsert_watch(
                            mint=mint, started_at=started.isoformat(), status="FAILED",
                            resumed=resumed, stop_reason=reason, pool=migration.pool,
                        )
                        return
                    if action == "investigate":
                        if mem is not None and any(
                            str(r.get("mint")) == mint for r in getattr(mem, "investigations", []) or []
                        ):
                            investigated = True
                            await self._record_followup_tick(migration, snap)
                        else:
                            await self._trace(
                                mint=mint,
                                kind="gate1",
                                message=f"Gate 1 qualified ${round(snap.volume_m5_usd, 0):.0f} / 5m",
                                extra={"volume_m5_usd": snap.volume_m5_usd},
                            )
                            await self._investigate_and_maybe_alert(migration, snap)
                            investigated = True
                            await self._trace(mint=mint, kind="investigation", message="Investigation created")
                            await self._record_followup_tick(migration, snap)
                    elif action == "tick":
                        await self._record_followup_tick(migration, snap)
                    ticks_n = 0
                    if mem is not None:
                        ticks_n = sum(1 for t in mem.market_ticks if t.mint == mint)
                    await self._upsert_watch(
                        mint=mint,
                        started_at=started.isoformat(),
                        status="WATCHING" if investigated else "DETECTED",
                        resumed=resumed,
                        last_observation_at=snap.fetched_at.isoformat() if snap.fetched_at else datetime.now(timezone.utc).isoformat(),
                        observation_count=ticks_n,
                        pool=migration.pool,
                        persistence_status="WRITTEN",
                    )
                await asyncio.sleep(self._interval)

            logger.info(
                "volume.watch_timeout",
                mint=mint,
                threshold_usd=self._threshold,
                watched_sec=round((datetime.now(timezone.utc) - started).total_seconds(), 1),
            )
            await self._upsert_watch(
                mint=mint, started_at=started.isoformat(), status="COMPLETED", resumed=resumed, pool=migration.pool,
            )
            await self._trace(mint=mint, kind="watch_complete", message="T+1800 window complete")
        except Exception as exc:
            logger.error("volume.watch_failed", mint=mint, error=str(exc))
            await self._trace(mint=mint, kind="watch_error", message=f"Watch failed: {str(exc)[:160]}")
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

    async def _persist_intelligence_decision(
        self, inv: Any, snap: VolumeSnapshot, *, alert_ok: bool, alert_reason: str | None
    ) -> None:
        """Durable compact decision row. Fail-soft. Never fabricates fields."""
        try:
            import json
            from stinky_core.memory import MEMORY_INSERT_DECISION

            compact = {
                "mint": inv.mint,
                "decision_timestamp": datetime.now(timezone.utc).isoformat(),
                "protocol": snap.dex_id,
                "volume_m5_usd": snap.volume_m5_usd,
                "pipeline_status": inv.pipeline_status,
                "has_intelligence": bool(inv.has_intelligence),
                "promote": bool(inv.promote),
                "stinky_score": inv.score.score if inv.score else None,
                "alert_ok": bool(alert_ok),
                "alert_reason": alert_reason,
                "synthetic_level": inv.synthetic.level if inv.synthetic else None,
                "rug_level": inv.rug.level if inv.rug else None,
                "outcome_label": None,
                "label_version": None,
                "model_version": getattr(inv, "model_version", None),
            }
            params = dict(compact)
            params["row"] = json.dumps(compact, default=str)
            mem = getattr(self, "_memory", None)
            if mem is not None:
                mem.record_decision(compact)
            async with self._sessions() as session:
                await session.execute(text(MEMORY_INSERT_DECISION), params)
                await session.commit()
        except Exception as exc:
            logger.warning(
                "intelligence_decision.persist_failed",
                mint=getattr(inv, "mint", None),
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
                MEMORY_SELECT_DECISION,
                MEMORY_SELECT_FINGERPRINT,
                MEMORY_SELECT_FINGERPRINT_OUTCOME,
                MEMORY_SELECT_INVESTIGATION,
                MEMORY_SELECT_MARKET_OBS,
                MEMORY_SELECT_QUALITY,
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
                try:
                    decs = (await session.execute(text(MEMORY_SELECT_DECISION))).mappings().all()
                except Exception:
                    decs = []
                try:
                    ticks = (await session.execute(text(MEMORY_SELECT_MARKET_OBS))).mappings().all()
                except Exception:
                    ticks = []
                try:
                    invs = (await session.execute(text(MEMORY_SELECT_INVESTIGATION))).mappings().all()
                except Exception:
                    invs = []
                try:
                    qstates = (await session.execute(text(MEMORY_SELECT_QUALITY))).mappings().all()
                except Exception:
                    qstates = []
            self._memory.hydrate({
                "wallet_obs": [dict(r) for r in wobs],
                "wallet_outcomes": [dict(r) for r in wout],
                "creator_obs": [dict(r) for r in cobs],
                "creator_outcomes": [dict(r) for r in cout],
                "fingerprints": [dict(r) for r in fps],
                "fingerprint_outcomes": [dict(r) for r in fpout],
                "decisions": [dict(r) for r in decs],
                "market_ticks": [dict(r) for r in ticks],
                "investigations": [dict(r) for r in invs],
                "quality_states": [dict(r) for r in qstates],
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
        features: dict[str, Any] | None = None,
        volume_m5_usd: float | None = None,
        price_usd: float | None = None,
        liquidity_usd: float | None = None,
        market_cap_usd: float | None = None,
        buys: int | None = None,
        sells: int | None = None,
        investigation: dict[str, Any] | None = None,
    ) -> None:
        try:
            from stinky_core.memory import (
                MEMORY_INSERT_CREATOR_OBS,
                MEMORY_INSERT_FINGERPRINT,
                MEMORY_INSERT_INVESTIGATION,
                MEMORY_INSERT_MARKET_OBS,
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
                            "side": str(b.get("side") or b.get("type") or "buy"),
                            "entry_price": b.get("entry_price") if b.get("entry_price") is not None else b.get("price"),
                            "exit_size": b.get("exit_size"),
                            "exit_price": b.get("exit_price"),
                            "ret_pct": b.get("ret_pct") if b.get("ret_pct") is not None else b.get("return_pct"),
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
                            "features": json.dumps(features or {}),
                        },
                    )
                await session.execute(
                    text(MEMORY_INSERT_MARKET_OBS),
                    {
                        "mint": mint,
                        "observed_at": observed_at,
                        "volume_m5_usd": volume_m5_usd,
                        "price_usd": price_usd,
                        "liquidity_usd": liquidity_usd,
                        "source": "observed",
                        "market_cap_usd": market_cap_usd,
                        "buys": buys,
                        "sells": sells,
                        "txns": (buys or 0) + (sells or 0) if (buys is not None or sells is not None) else None,
                        "unique_buyers": None,
                        "unique_sellers": None,
                        "volume_since_gate": None,
                    },
                )
                if investigation and investigation.get("mint"):
                    rec = investigation
                    await session.execute(
                        text(MEMORY_INSERT_INVESTIGATION),
                        {
                            "mint": rec.get("mint") or mint,
                            "gate1_at": rec.get("gate1_at") or observed_at,
                            "discovered_at": rec.get("discovered_at") or rec.get("gate1_at") or observed_at,
                            "protocol": rec.get("protocol"),
                            "volume_5m_at_gate": rec.get("volume_5m_at_gate"),
                            "liquidity_at_gate": rec.get("liquidity_at_gate"),
                            "market_cap_at_gate": rec.get("market_cap_at_gate"),
                            "price_at_gate": rec.get("price_at_gate"),
                            "pair_identifier": rec.get("pair_identifier"),
                            "creator": rec.get("creator"),
                            "gate_decision": rec.get("gate_decision") or "PASSED",
                            "investigation_status": rec.get("investigation_status"),
                            "correlation_id": rec.get("correlation_id"),
                            "row": json.dumps(rec, default=str),
                        },
                    )
                await session.commit()
        except Exception as exc:
            logger.warning("memory.persist_failed", mint=mint, error=str(exc)[:200])

    async def _record_followup_tick(self, migration: DetectedMigration, snap: VolumeSnapshot) -> None:
        """Post-Gate-1 market tick. Missing fields stay None. Never interpolates."""
        mint = migration.mint
        at = snap.fetched_at.isoformat() if snap.fetched_at else datetime.now(timezone.utc).isoformat()
        buys = snap.txns_m5_buys
        sells = snap.txns_m5_sells
        txns = (buys or 0) + (sells or 0) if (buys is not None or sells is not None) else None
        mem = getattr(self, "_memory", None)
        if mem is not None:
            mem.record_market_tick(
                mint=mint,
                observed_at=at,
                volume_m5_usd=snap.volume_m5_usd,
                price_usd=snap.price_usd,
                liquidity_usd=snap.liquidity_usd,
                market_cap_usd=getattr(snap, "market_cap_usd", None),
                buys=buys,
                sells=sells,
                txns=txns,
                source="observed",
            )
            try:
                from stinky_core.quality_state import evaluate_quality_state

                rec = next((r for r in mem.investigations if r.get("mint") == mint), None)
                t0 = (rec or {}).get("gate1_at") or (rec or {}).get("decision_timestamp")
                if t0:
                    prev = next((q.get("state") for q in reversed(mem.quality_states) if q.get("mint") == mint), None)
                    st = evaluate_quality_state(mem, mint=mint, t0=t0, as_of=at, previous_state=prev)
                    if mem.record_quality_state(st):
                        if self._sessions:
                            await self._persist_quality_state(st)
                        await self._trace(
                            mint=mint,
                            kind="quality",
                            message=f"{st.get('previous_state')} → {st.get('state')}",
                            extra={
                                "state": st.get("state"),
                                "previous_state": st.get("previous_state"),
                                "why": st.get("why"),
                                "evidence_quality": st.get("evidence_quality"),
                            },
                        )
                        try:
                            if st.get("state") != st.get("previous_state"):
                                evt = Event(
                                    event_type=EventType.QUALITY_STATE_CHANGED,
                                    payload={
                                        "mint": mint,
                                        "previous_state": st.get("previous_state"),
                                        "current_state": st.get("state"),
                                        "state": st.get("state"),
                                        "severity": st.get("severity"),
                                        "why": st.get("why"),
                                        "evidence_quality": st.get("evidence_quality"),
                                        "unknown": st.get("unknown"),
                                        "as_of": st.get("as_of"),
                                        "not_a_buy": True,
                                        "calibrated_probability": False,
                                    },
                                    producer="sentinel-volume",
                                )
                                await self._publisher.publish_raw_event(evt, kind="quality")
                        except Exception as exc:
                            logger.debug("quality.publish_failed", mint=mint, error=str(exc)[:200])
            except Exception as exc:
                logger.debug("quality.eval_failed", mint=mint, error=str(exc)[:200])
        if not self._sessions:
            return
        try:
            from stinky_core.memory import MEMORY_INSERT_MARKET_OBS

            async with self._sessions() as session:
                await session.execute(
                    text(MEMORY_INSERT_MARKET_OBS),
                    {
                        "mint": mint,
                        "observed_at": at,
                        "volume_m5_usd": snap.volume_m5_usd,
                        "price_usd": snap.price_usd,
                        "liquidity_usd": snap.liquidity_usd,
                        "source": "observed",
                        "market_cap_usd": getattr(snap, "market_cap_usd", None),
                        "buys": buys,
                        "sells": sells,
                        "txns": txns,
                        "unique_buyers": None,
                        "unique_sellers": None,
                        "volume_since_gate": None,
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.debug("observation.tick_persist_failed", mint=mint, error=str(exc)[:200])

    async def _persist_quality_state(self, row: dict[str, Any]) -> None:
        if not self._sessions:
            return
        try:
            import json
            from stinky_core.memory import MEMORY_INSERT_QUALITY

            async with self._sessions() as session:
                await session.execute(
                    text(MEMORY_INSERT_QUALITY),
                    {
                        "mint": row.get("mint"),
                        "as_of": row.get("as_of"),
                        "state": row.get("state"),
                        "previous_state": row.get("previous_state"),
                        "severity": row.get("severity"),
                        "row": json.dumps(row, default=str),
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.debug("quality.persist_failed", mint=row.get("mint"), error=str(exc)[:200])

    async def _trace(self, *, mint: str, kind: str, message: str, extra: dict[str, Any] | None = None) -> None:
        rec = {
            "mint": mint,
            "at": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "message": message,
            "evidence_label": "LIVE",
            **(extra or {}),
        }
        mem = getattr(self, "_memory", None)
        if mem is not None:
            mem.record_operator_event(rec)
        if not self._sessions:
            return
        try:
            import json
            from stinky_core.memory import MEMORY_INSERT_OPERATOR_EVENT

            async with self._sessions() as session:
                await session.execute(
                    text(MEMORY_INSERT_OPERATOR_EVENT),
                    {
                        "mint": mint,
                        "at": rec["at"],
                        "kind": kind,
                        "message": message,
                        "evidence_label": "LIVE",
                        "row": json.dumps(rec, default=str),
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.debug("operator.event_persist_failed", mint=mint, error=str(exc)[:160])

    async def _upsert_watch(self, *, mint: str, started_at: str, status: str, resumed: bool = False, **extra: Any) -> None:
        rec = {
            "mint": mint,
            "started_at": started_at,
            "status": status,
            "resumed": resumed,
            "interrupted": extra.get("interrupted") or False,
            "last_observation_at": extra.get("last_observation_at"),
            "observation_count": extra.get("observation_count"),
            "persistence_status": extra.get("persistence_status") or "UNKNOWN",
            "stop_reason": extra.get("stop_reason"),
            "pool": extra.get("pool"),
            "evidence_label": "LIVE",
        }
        mem = getattr(self, "_memory", None)
        if mem is not None:
            mem.record_watch_state(rec)
            rec["persistence_status"] = extra.get("persistence_status") or rec["persistence_status"]
        if not self._sessions:
            rec["persistence_status"] = "NO_SESSION"
            if mem is not None:
                mem.record_watch_state(rec)
            return
        try:
            import json
            from stinky_core.memory import MEMORY_INSERT_WATCH_STATE

            async with self._sessions() as session:
                await session.execute(
                    text(MEMORY_INSERT_WATCH_STATE),
                    {
                        "mint": mint,
                        "started_at": started_at,
                        "last_observation_at": rec.get("last_observation_at"),
                        "observation_count": rec.get("observation_count"),
                        "next_due_at": extra.get("next_due_at"),
                        "status": status,
                        "resumed": resumed,
                        "interrupted": bool(rec.get("interrupted")),
                        "persistence_status": "WRITTEN",
                        "stop_reason": rec.get("stop_reason"),
                        "row": json.dumps({**rec, "persistence_status": "WRITTEN"}, default=str),
                    },
                )
                await session.commit()
            rec["persistence_status"] = "WRITTEN"
            if mem is not None:
                mem.record_watch_state(rec)
        except Exception as exc:
            rec["persistence_status"] = "FAILED"
            if mem is not None:
                mem.record_watch_state(rec)
            logger.debug("watch.persist_failed", mint=mint, error=str(exc)[:160])

    async def _record_probe(self, probe: dict[str, Any]) -> None:
        mem = getattr(self, "_memory", None)
        if mem is not None:
            mem.record_provider_probe(probe)
        if not self._sessions:
            return
        try:
            import json
            from stinky_core.memory import MEMORY_INSERT_PROVIDER_PROBE

            async with self._sessions() as session:
                await session.execute(
                    text(MEMORY_INSERT_PROVIDER_PROBE),
                    {
                        "provider": probe.get("provider") or "dexscreener",
                        "at": probe.get("at"),
                        "status": probe.get("status") or "UNKNOWN",
                        "latency_ms": probe.get("latency_ms"),
                        "last_success_at": probe.get("last_success_at") or (probe.get("at") if probe.get("ok") else None),
                        "last_failure_at": probe.get("last_failure_at") or (probe.get("at") if probe.get("ok") is False else None),
                        "error": probe.get("error"),
                        "row": json.dumps(probe, default=str),
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.debug("probe.persist_failed", error=str(exc)[:160])

    async def _investigate_and_maybe_alert(
        self, migration: DetectedMigration, snap: VolumeSnapshot
    ) -> bool:
        """Deep inspect after Gate 1. Returns True if an ALERT_CANDIDATE was emitted."""
        mint = migration.mint
        try:
            from stinky_core.metrics import ENGINE_LOG

            cid = ENGINE_LOG.new_correlation_id(mint)
            ENGINE_LOG.emit(
                "GATE_PASSED",
                mint=mint,
                correlation_id=cid,
                decision="GATE1",
                reason="volume_m5",
                extra={"volume_m5_usd": snap.volume_m5_usd},
            )
        except Exception:
            cid = None
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
            "market_cap_usd": getattr(snap, "market_cap_usd", None),
            "price_usd": snap.price_usd,
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
                    features=inv.fingerprint_features,
                )
                if inv.investigation_record:
                    rec = dict(inv.investigation_record)
                    rec["evidence_label"] = "LIVE"
                    mem.record_investigation(rec)
                mem.record_market_tick(
                    mint=mint,
                    observed_at=bundle.get("decision_timestamp"),
                    volume_m5_usd=snap.volume_m5_usd,
                    price_usd=snap.price_usd,
                    liquidity_usd=snap.liquidity_usd,
                    market_cap_usd=getattr(snap, "market_cap_usd", None),
                    buys=snap.txns_m5_buys,
                    sells=snap.txns_m5_sells,
                    txns=(snap.txns_m5_buys or 0) + (snap.txns_m5_sells or 0)
                    if snap.txns_m5_buys is not None or snap.txns_m5_sells is not None
                    else None,
                )
                await self._persist_memory_decision(
                    mint=mint,
                    observed_at=bundle.get("decision_timestamp"),
                    buyers=buyers_rows,
                    creator=migration.creator,
                    fingerprint=inv.fingerprint,
                    features=inv.fingerprint_features,
                    volume_m5_usd=snap.volume_m5_usd,
                    price_usd=snap.price_usd,
                    liquidity_usd=snap.liquidity_usd,
                    market_cap_usd=getattr(snap, "market_cap_usd", None),
                    buys=snap.txns_m5_buys,
                    sells=snap.txns_m5_sells,
                    investigation=inv.investigation_record,
                )
            except Exception:
                pass
        alert_ok, alert_reason = can_alert_investigation(True, inv)
        if alert_ok:
            inv.pipeline_status = "ALERT"
        await self._persist_inspection(
            inspection_persist_params(inv, alert_ok=alert_ok, alert_reason=alert_reason)
        )
        await self._persist_intelligence_decision(inv, snap, alert_ok=alert_ok, alert_reason=alert_reason)

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
            correlation_id=getattr(inv, "correlation_id", None) or cid,
            findings=len(getattr(inv, "findings", None) or []),
            model=INTEL_VERSION,
        )
        try:
            from stinky_core.metrics import ENGINE_LOG

            ENGINE_LOG.emit(
                "PROMOTION_DECISION" if not alert_ok else "ALERT",
                mint=mint,
                correlation_id=getattr(inv, "correlation_id", None) or cid,
                decision="ALERT" if alert_ok else inv.pipeline_status,
                reason=alert_reason,
                evidence_counts={"findings": len(getattr(inv, "findings", None) or [])},
            )
        except Exception:
            pass

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
