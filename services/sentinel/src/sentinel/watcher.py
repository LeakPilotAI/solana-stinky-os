"""WebSocket logsSubscribe watcher for pump.fun creates."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
import websockets
from websockets.exceptions import ConnectionClosed

try:
    from websockets.exceptions import InvalidStatus as _InvalidStatus
except ImportError:  # older websockets
    try:
        from websockets.exceptions import InvalidStatusCode as _InvalidStatus
    except ImportError:
        _InvalidStatus = type("InvalidStatus", (Exception,), {})  # type: ignore[misc,assignment]

from sentinel.config import settings
from sentinel.history import WalletHistory
from sentinel.models import DetectedLaunch
from sentinel.pumpfun import PUMP_FUN_PROGRAM, parse_logs_notification
from sentinel.publisher import LaunchPublisher
from sentinel.rate_limit import gate, is_rate_limit_error
from sentinel.rpc import SolanaRPC
from sentinel.score import score_deployer

logger = structlog.get_logger(__name__)


class PumpFunWatcher:
    """Subscribe to pump.fun program logs and emit DetectedLaunch events."""

    def __init__(
        self,
        publisher: LaunchPublisher,
        rpc: SolanaRPC,
        history: WalletHistory | None = None,
    ) -> None:
        self._publisher = publisher
        self._rpc = rpc
        self._history = history or WalletHistory(rpc)
        self._seen_sigs: set[str] = set()
        self._seen_mints: set[str] = set()
        self._running = False

    def _ws_url(self) -> str:
        if settings.helius_api_key and not gate.tripped:
            return f"wss://mainnet.helius-rpc.com/?api-key={settings.helius_api_key}"
        if settings.helius_api_key and gate.tripped:
            # Still use Helius after cooldown — public WS lacks the same reliability for logs
            return f"wss://mainnet.helius-rpc.com/?api-key={settings.helius_api_key}"
        return settings.solana_ws_url

    def _remember(self, launch: DetectedLaunch) -> bool:
        """Return True if this is new; False if duplicate."""
        if launch.mint in self._seen_mints:
            return False
        if launch.signature and launch.signature in self._seen_sigs:
            return False
        self._seen_mints.add(launch.mint)
        if launch.signature:
            self._seen_sigs.add(launch.signature)
        if len(self._seen_mints) > 10_000:
            self._seen_mints = set(list(self._seen_mints)[-5_000:])
        if len(self._seen_sigs) > 10_000:
            self._seen_sigs = set(list(self._seen_sigs)[-5_000:])
        return True

    async def _handle_launch(self, launch: DetectedLaunch) -> None:
        if not self._remember(launch):
            return

        logger.info(
            "launch.detected",
            mint=launch.mint,
            deployer=launch.deployer,
            name=launch.name,
            symbol=launch.symbol,
            signature=launch.signature,
        )

        try:
            summary = await self._history.summarize(launch.deployer)
            logger.info(
                "launch.creator_history",
                deployer=launch.deployer,
                stored_launches=summary.launch_count,
                first_seen=summary.first_seen.isoformat() if summary.first_seen else None,
                note=summary.note,
            )
        except Exception as exc:
            logger.warning("launch.history_failed", error=str(exc))
            from sentinel.models import WalletSummary

            summary = WalletSummary(address=launch.deployer, note=f"history error: {exc}")

        result = score_deployer(summary, has_name=bool(launch.name or launch.symbol))
        logger.info(
            "launch.stinky_score",
            deployer=launch.deployer,
            mint=launch.mint,
            score=result.score,
            confidence=result.confidence,
            model=result.model_version,
            explanation=result.explanation,
        )

        await self._publisher.publish(launch)

    async def _process_message(self, raw: str | bytes) -> None:
        try:
            msg: dict[str, Any] = json.loads(raw)
        except Exception:
            return

        if "result" in msg and "id" in msg and "method" not in msg:
            logger.info("watcher.subscribed", result=msg.get("result"))
            return

        if msg.get("method") != "logsNotification":
            return

        params = msg.get("params") or {}
        result = params.get("result") or {}
        launch = parse_logs_notification(result)
        if launch:
            await self._handle_launch(launch)

    def _next_delay(self, current: float, *, rate_limited: bool) -> float:
        if rate_limited:
            return gate.trip("watcher_ws_429")
        return min(current * 1.5, settings.max_reconnect_delay_sec)

    async def run(self) -> None:
        self._running = True
        delay = settings.reconnect_delay_sec
        program = settings.pump_fun_program or PUMP_FUN_PROGRAM

        while self._running:
            await gate.wait_if_needed(label="create_watcher")
            url = self._ws_url()
            rate_limited = False
            try:
                logger.info("watcher.connecting", url=url.split("?")[0], program=program)
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    sub = {
                        "jsonrpc": "2.0",
                        "id": 1,
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
                    "watcher.connection_closed", code=exc.code, reason=str(exc.reason)
                )
                if is_rate_limit_error(exc) or exc.code in (1008, 1013):
                    # 1008 policy / 1013 try again later often used under load
                    rate_limited = is_rate_limit_error(exc) or "429" in str(exc.reason)
            except _InvalidStatus as exc:
                status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
                rate_limited = is_rate_limit_error(exc) or status == 429
                logger.error("watcher.error", error=str(exc))
                if rate_limited:
                    gate.trip(str(exc))
            except Exception as exc:
                err = str(exc)
                rate_limited = is_rate_limit_error(exc) or "429" in err
                logger.error("watcher.error", error=err)
                if rate_limited:
                    gate.trip(err)

            if not self._running:
                break

            # Hard path: any 429 → process-wide cooldown (never 60s storm)
            if rate_limited or gate.tripped or "429" in str(rate_limited):
                cd = gate.trip("create_watcher_429") if rate_limited else gate.remaining_sec
                logger.warning(
                    "helius.rate_limited",
                    label="create_watcher",
                    cooldown_sec=round(float(cd) if cd else gate.remaining_sec, 1),
                    message="Pausing reconnect — free Helius quota. Not a crash.",
                )
                await gate.wait_if_needed(label="create_watcher")
                delay = settings.reconnect_delay_sec
            else:
                delay = self._next_delay(delay, rate_limited=False)
                logger.info("watcher.reconnect_in", seconds=round(delay, 1))
                await asyncio.sleep(delay)

    def stop(self) -> None:
        self._running = False
