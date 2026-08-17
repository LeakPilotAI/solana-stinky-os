"""High-volume pump discovery ? backfills mints migration WS may have missed.

Polls DexScreener public endpoints for Solana pump mints with strong 5m volume,
persists market_snapshots, runs the same Birdeye fee gate, and hands qualified
mints to VolumeMonitor so Live Runners / Alerts / Trending stay consistent.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from sentinel.config import settings
from sentinel.models import DetectedMigration
from sentinel.volume import DexScreenerClient, fetch_pump_fees_sol

if TYPE_CHECKING:
    from sentinel.volume import VolumeMonitor

logger = structlog.get_logger(__name__)

BOOSTS_URL = "https://api.dexscreener.com/token-boosts/top/v1"
PROFILES_URL = "https://api.dexscreener.com/token-profiles/latest/v1"


class HighVolumeDiscovery:
    """Periodic scan so explosive pumps still enter the OS if migrate was missed."""

    def __init__(
        self,
        volume: "VolumeMonitor",
        *,
        interval_sec: float = 45.0,
        min_volume_usd: float | None = None,
    ) -> None:
        self._volume = volume
        self._interval = float(interval_sec)
        # Discovery uses the same runner floor (default 50k) so CC/runners fill;
        # Trending still requires 100k via API.
        self._min_vol = float(
            min_volume_usd
            if min_volume_usd is not None
            else getattr(settings, "volume_threshold_usd", 50_000.0) or 50_000.0
        )
        self._stop = asyncio.Event()
        self._seen: set[str] = set()
        self._client = DexScreenerClient()

    def stop(self) -> None:
        self._stop.set()

    async def close(self) -> None:
        self.stop()
        await self._client.close()

    async def run(self) -> None:
        logger.info(
            "discovery.starting",
            interval_sec=self._interval,
            min_volume_usd=self._min_vol,
        )
        # Stagger first poll so migration watcher connects first
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=15.0)
            return
        except asyncio.TimeoutError:
            pass
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception as exc:
                logger.warning("discovery.tick_failed", error=str(exc)[:300])
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
                break
            except asyncio.TimeoutError:
                continue
        logger.info("discovery.stopped")

    async def _tick(self) -> None:
        mints = await self._collect_candidate_mints()
        if not mints:
            logger.debug("discovery.no_candidates")
            return
        logger.info("discovery.candidates", n=len(mints))
        for mint in mints:
            if mint in self._seen and mint in getattr(self._volume, "_active", set()):
                continue
            try:
                await self._evaluate_mint(mint)
            except Exception as exc:
                logger.warning("discovery.mint_failed", mint=mint, error=str(exc)[:200])
            await asyncio.sleep(0.35)  # be gentle to DexScreener / Birdeye

    async def _collect_candidate_mints(self) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()
        async with httpx.AsyncClient(timeout=15.0) as http:
            for url in (BOOSTS_URL, PROFILES_URL):
                try:
                    resp = await http.get(url)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                except Exception:
                    continue
                rows = data if isinstance(data, list) else []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    chain = str(row.get("chainId") or row.get("chain") or "").lower()
                    if chain and chain not in ("solana", "sol"):
                        continue
                    addr = (
                        row.get("tokenAddress")
                        or row.get("address")
                        or (row.get("token") or {}).get("address")
                    )
                    if not addr or not isinstance(addr, str):
                        continue
                    mint = addr.strip()
                    if not mint.lower().endswith("pump"):
                        continue
                    if mint in seen:
                        continue
                    seen.add(mint)
                    found.append(mint)
        return found[:40]

    async def _evaluate_mint(self, mint: str) -> None:
        snap = await self._client.fetch_volume(mint)
        if not snap or snap.volume_m5_usd is None:
            return
        vol = float(snap.volume_m5_usd or 0)
        if vol + 1e-9 < self._min_vol:
            return

        # Persist snapshot via volume monitor so Trending has measured data
        persist = getattr(self._volume, "_persist_market_snapshot", None)
        if callable(persist):
            await persist(mint, snap)

        fees = await fetch_pump_fees_sol(self._client._http, mint)
        snap.fees_sol = fees
        ok, reason = self._volume._passes_pump_quality(mint, snap, fees)
        fees_verified = fees is not None and fees == fees and fees >= 0

        await self._volume._record_filter_eval(
            mint=mint,
            accepted=bool(ok),
            reason=reason if not ok else "DISCOVERY_PASS",
            fees_sol=fees,
            fees_verified=fees_verified,
            snap=snap,
        )
        logger.info(
            "discovery.evaluated",
            mint=mint,
            volume_m5_usd=round(vol, 2),
            fees_sol=fees,
            quality_ok=ok,
            quality_reason=reason,
        )
        if not ok:
            return

        # Hand to volume watch (emit path / scoring) if not already active
        self._seen.add(mint)
        mig = DetectedMigration(
            mint=mint,
            pool=snap.pair_address or "",
            creator=None,
            destination=str(snap.dex_id or "pumpswap"),
            source="discovery-high-volume",
            block_time=datetime.now(timezone.utc),
        )
        self._volume.watch(mig)
        logger.info(
            "discovery.watch_started",
            mint=mint,
            volume_m5_usd=round(vol, 2),
            fees_sol=fees,
        )
