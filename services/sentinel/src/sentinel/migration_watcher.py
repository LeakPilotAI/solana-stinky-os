"""WebSocket logsSubscribe watcher for pump.fun → PumpSwap migrations.

PUBLIC-RPC-ONLY (v1):
  - Never opens Helius WebSocket from this watcher. Helius is optional enrichment.
  - Always uses public / configured Solana WS for logsSubscribe.
  - Helius API key is ignored for WS even if present in .env.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
import websockets
from websockets.exceptions import ConnectionClosed

try:
    from websockets.exceptions import InvalidStatus as _InvalidStatus
except ImportError:
    try:
        from websockets.exceptions import InvalidStatusCode as _InvalidStatus
    except ImportError:
        _InvalidStatus = type("InvalidStatus", (Exception,), {})  # type: ignore[misc,assignment]

from sentinel.config import settings
from sentinel.migration import (
    MIGRATION_PROGRAM,
    looks_like_migrate_attempt,
    parse_migration_from_transaction,
    parse_migration_logs,
)
from sentinel.models import DetectedMigration
from sentinel.publisher import LaunchPublisher
from sentinel.rate_limit import gate, is_rate_limit_error
from sentinel.rpc import SolanaRPC
from sentinel.volume import VolumeMonitor

logger = structlog.get_logger(__name__)


class MigrationWatcher:
    """Subscribe to migration program logs; emit DetectedMigration on graduation."""

    def __init__(
        self,
        publisher: LaunchPublisher,
        volume_monitor: VolumeMonitor | None = None,
        rpc: SolanaRPC | None = None,
    ) -> None:
        self._publisher = publisher
        self._volume = volume_monitor
        self._rpc = rpc or SolanaRPC()
        self._seen_mints: set[str] = set()
        self._seen_sigs: set[str] = set()
        self._running = False
        self._cnt_notifications = 0
        self._cnt_migrate_attempts = 0
        self._cnt_parsed_ws = 0
        self._cnt_parsed_rpc = 0
        self._cnt_missed = 0
        self._cnt_published = 0

    def _ws_url(self) -> str:
        """NEVER use Helius WS — public / configured Solana WS only."""
        url = (
            getattr(settings, "public_ws_url", None)
            or getattr(settings, "solana_ws_url", None)
            or "wss://api.mainnet-beta.solana.com"
        )
        url = str(url).strip()
        # Safety: if someone put a Helius URL in solana_ws_url, force public
        if "helius" in url.lower():
            logger.warning(
                "migration_watcher.helius_ws_blocked",
                configured=url.split("?")[0],
                using="wss://api.mainnet-beta.solana.com",
            )
            return "wss://api.mainnet-beta.solana.com"
        return url

    def _remember(self, mig: DetectedMigration) -> bool:
        if mig.mint in self._seen_mints:
            return False
        if mig.signature and mig.signature in self._seen_sigs:
            return False
        self._seen_mints.add(mig.mint)
        if mig.signature:
            self._seen_sigs.add(mig.signature)
        if len(self._seen_mints) > 10_000:
            self._seen_mints = set(list(self._seen_mints)[-5_000:])
        return True

    def _log_stats(self) -> None:
        logger.info(
            "migration_watcher.stats",
            notifications=self._cnt_notifications,
            migrate_attempts=self._cnt_migrate_attempts,
            parsed_ws=self._cnt_parsed_ws,
            parsed_rpc=self._cnt_parsed_rpc,
            missed=self._cnt_missed,
            published=self._cnt_published,
            ws_mode="public",
        )

    async def _handle(self, mig: DetectedMigration) -> None:
        if not self._remember(mig):
            return

        self._cnt_published += 1
        logger.info(
            "migration.detected",
            mint=mig.mint,
            pool=mig.pool,
            creator=mig.creator,
            destination=mig.destination,
            quote_amount_in=mig.quote_amount_in,
            signature=mig.signature,
            source=mig.source,
            published=self._cnt_published,
        )
        await self._publisher.publish_migration(mig)

        if self._volume is not None:
            self._volume.watch(mig)

        if self._cnt_published % 10 == 0:
            self._log_stats()

    async def _try_rpc_rescue(self, signature: str | None) -> DetectedMigration | None:
        if not signature:
            return None
        try:
            tx = await self._rpc.get_transaction(signature)
            if not tx:
                logger.warning("migration.rpc_tx_empty", signature=signature)
                return None
            mig = parse_migration_from_transaction(tx, signature=signature)
            if mig:
                self._cnt_parsed_rpc += 1
                logger.info(
                    "migration.rpc_rescued",
                    mint=mig.mint,
                    pool=mig.pool,
                    signature=signature,
                )
                return mig
            logger.warning("migration.rpc_parse_failed", signature=signature)
            return None
        except Exception as exc:
            if is_rate_limit_error(exc):
                gate.trip(str(exc))
            logger.warning("migration.rpc_rescue_error", signature=signature, error=str(exc))
            return None

    async def _process_message(self, raw: str | bytes) -> None:
        try:
            msg: dict[str, Any] = json.loads(raw)
        except Exception:
            return

        if "result" in msg and "id" in msg and "method" not in msg:
            logger.info(
                "migration_watcher.subscribed",
                result=msg.get("result"),
                ws_mode="public",
            )
            return

        if msg.get("method") != "logsNotification":
            return

        self._cnt_notifications += 1
        params = msg.get("params") or {}
        result = params.get("result") or {}
        value = result.get("value") or result
        signature = value.get("signature")

        mig = parse_migration_logs(result)
        if mig:
            self._cnt_parsed_ws += 1
            await self._handle(mig)
            return

        if looks_like_migrate_attempt(result):
            self._cnt_migrate_attempts += 1
            mig = await self._try_rpc_rescue(signature)
            if mig:
                await self._handle(mig)
                return
            self._cnt_missed += 1
            logger.warning(
                "migration.missed_after_rpc",
                signature=signature,
                missed_total=self._cnt_missed,
            )

    def _next_delay(self, current: float) -> float:
        return min(current * 1.5, settings.max_reconnect_delay_sec)

    async def run(self) -> None:
        self._running = True
        delay = settings.reconnect_delay_sec
        program = MIGRATION_PROGRAM

        start_delay = float(getattr(settings, "migration_watcher_start_delay_sec", 2.0) or 0.0)
        if start_delay > 0:
            await asyncio.sleep(start_delay)

        while self._running:
            url = self._ws_url()
            try:
                logger.info(
                    "migration_watcher.connecting",
                    url=url.split("?")[0],
                    program=program,
                    ws_mode="public",
                    note="helius_ws_disabled",
                )
                async with websockets.connect(
                    url, ping_interval=20, ping_timeout=20, max_size=32 * 1024 * 1024
                ) as ws:
                    sub = {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "logsSubscribe",
                        "params": [
                            {"mentions": [program]},
                            {"commitment": settings.commitment},
                        ],
                    }
                    await ws.send(json.dumps(sub))
                    delay = settings.reconnect_delay_sec

                    async for message in ws:
                        if not self._running:
                            break
                        await self._process_message(message)

            except ConnectionClosed as exc:
                logger.warning(
                    "migration_watcher.connection_closed",
                    code=exc.code,
                    reason=str(exc.reason),
                )
                self._log_stats()
            except _InvalidStatus as exc:
                logger.error("migration_watcher.error", error=str(exc))
                self._log_stats()
            except Exception as exc:
                logger.error("migration_watcher.error", error=str(exc))
                self._log_stats()

            if not self._running:
                break

            delay = self._next_delay(delay)
            logger.info("migration_watcher.reconnect_in", seconds=round(delay, 1))
            await asyncio.sleep(delay)

    def stop(self) -> None:
        self._running = False
