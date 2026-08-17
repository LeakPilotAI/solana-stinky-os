"""Consume ALERT_CANDIDATE events and DM subscribed users only.

High-potential only: migration + volume threshold + min Stinky Score.
Never every migration. Never creates.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import discord
import redis.asyncio as redis
import structlog

from discord_bot.config import settings
from discord_bot.store import Store

logger = structlog.get_logger(__name__)


class AlertDispatcher:
    def __init__(self, bot: discord.Client, store: Store) -> None:
        self._bot = bot
        self._store = store
        self._redis: redis.Redis | None = None
        self._running = False
        self._alerted_mints: set[str] = set()

    async def start(self) -> None:
        self._redis = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=10,
            socket_timeout=None,
            health_check_interval=30,
        )
        try:
            await self._redis.xgroup_create(
                settings.event_stream, settings.discord_consumer_group, id="0", mkstream=True
            )
        except Exception:
            pass  # group exists
        self._running = True
        asyncio.create_task(self._loop(), name="alert-dispatcher")

    async def stop(self) -> None:
        self._running = False
        if self._redis:
            await self._redis.aclose()

    async def _loop(self) -> None:
        assert self._redis is not None
        consumer = f"discord-{id(self)}"
        while self._running:
            try:
                rows = await self._redis.xreadgroup(
                    groupname=settings.discord_consumer_group,
                    consumername=consumer,
                    streams={settings.event_stream: ">"},
                    count=10,
                    block=5000,
                )
                if not rows:
                    continue
                for _stream, messages in rows:
                    for msg_id, fields in messages:
                        await self._handle(msg_id, fields)
            except Exception as exc:
                logger.warning("alerter.loop_error", error=str(exc))
                await asyncio.sleep(2)

    async def _handle(self, msg_id: str, fields: dict[str, str]) -> None:
        assert self._redis is not None
        try:
            raw = fields.get("data") or fields.get("payload") or ""
            if not raw:
                for v in fields.values():
                    if isinstance(v, str) and v.startswith("{"):
                        raw = v
                        break
            if not raw:
                await self._redis.xack(settings.event_stream, settings.discord_consumer_group, msg_id)
                return

            event = json.loads(raw)
            event_type = event.get("event_type") or event.get("type")
            if event_type != "alert.candidate":
                await self._redis.xack(settings.event_stream, settings.discord_consumer_group, msg_id)
                return

            payload = event.get("payload") or {}
            if not self._passes_quality_gate(payload):
                await self._redis.xack(settings.event_stream, settings.discord_consumer_group, msg_id)
                return

            mint = str(payload.get("mint") or "").strip()
            if mint and await self._already_alerted(mint):
                logger.info("alerter.dedupe_skip", mint=mint)
                await self._redis.xack(settings.event_stream, settings.discord_consumer_group, msg_id)
                return

            await self._dm_subscribers(payload)
            if mint:
                await self._mark_alerted(mint)
            await self._redis.xack(settings.event_stream, settings.discord_consumer_group, msg_id)
        except Exception as exc:
            logger.error("alerter.handle_failed", error=str(exc))
            try:
                await self._redis.xack(settings.event_stream, settings.discord_consumer_group, msg_id)
            except Exception:
                pass

    def _passes_quality_gate(self, payload: dict[str, Any]) -> bool:
        """High-potential only: pump + fees + score + meaningful early buyers.

        Volume ≥ threshold is already enforced by Sentinel before ALERT_CANDIDATE.
        """
        mint = str(payload.get("mint") or "?")
        score = payload.get("stinky_score")
        min_score = float(settings.alert_min_score)
        min_mb = int(settings.alert_min_meaningful_buyers)
        mb_raw = payload.get("meaningful_buyer_count")
        mb = int(mb_raw) if mb_raw is not None else None

        if getattr(settings, "require_pump_mint_suffix", True):
            if not mint.lower().endswith("pump"):
                logger.info("alerter.gate_blocked", mint=mint, reason="mint_not_pump_suffix")
                return False

        dex = str(payload.get("dex_id") or "").lower()
        denied = {x.strip().lower() for x in str(getattr(settings, "denied_dex_ids", "")).split(",") if x.strip()}
        allowed = {x.strip().lower() for x in str(getattr(settings, "allowed_dex_ids", "")).split(",") if x.strip()}
        if dex and dex in denied:
            logger.info("alerter.gate_blocked", mint=mint, reason="dex_denied", dex_id=dex)
            return False
        if allowed and dex and dex not in allowed:
            logger.info("alerter.gate_blocked", mint=mint, reason="dex_not_allowed", dex_id=dex)
            return False

        # HARD GATE: verified global fees paid (SOL). Fail-closed.
        # Missing / None / NaN / negative / malformed / < min → REJECT.
        # Do NOT default missing fees to 0 and accept.
        min_fees = float(getattr(settings, "min_fees_sol", 5.0) or 5.0)
        if min_fees > 0:
            fees_raw = payload.get("fees_sol")
            if fees_raw is None:
                fees_raw = payload.get("total_fees_sol")
            fees_verified = payload.get("global_fees_verified")
            if fees_verified is False:
                logger.info(
                    "alerter.gate_blocked",
                    mint=mint,
                    reason="GLOBAL_FEES_UNVERIFIED",
                    fees=fees_raw,
                    min_fees=min_fees,
                )
                return False
            if fees_raw is None:
                logger.info(
                    "alerter.gate_blocked",
                    mint=mint,
                    reason="GLOBAL_FEES_UNKNOWN",
                    min_fees=min_fees,
                )
                return False
            try:
                fees_f = float(fees_raw)
            except (TypeError, ValueError):
                logger.info(
                    "alerter.gate_blocked",
                    mint=mint,
                    reason="GLOBAL_FEES_INVALID",
                    fees=fees_raw,
                    min_fees=min_fees,
                )
                return False
            if fees_f != fees_f or fees_f < 0:  # NaN or negative
                logger.info(
                    "alerter.gate_blocked",
                    mint=mint,
                    reason="GLOBAL_FEES_INVALID",
                    fees=fees_f,
                    min_fees=min_fees,
                )
                return False
            # Safe compare: reject strictly below threshold (use epsilon for float)
            if fees_f + 1e-9 < min_fees:
                logger.info(
                    "alerter.gate_blocked",
                    mint=mint,
                    reason="LOW_GLOBAL_FEES",
                    fees=fees_f,
                    min_fees=min_fees,
                    global_fees_paid_sol=fees_f,
                    required=min_fees,
                )
                return False

        if score is None:
            logger.info(
                "alerter.gate_blocked",
                mint=mint,
                reason="missing_score",
                min_score=min_score,
            )
            return False

        score_f = float(score)
        if score_f < min_score:
            logger.info(
                "alerter.gate_blocked",
                mint=mint,
                reason="score_below_min",
                score=score_f,
                min_score=min_score,
                meaningful_buyers=mb,
                entity_launches=payload.get("entity_launch_count"),
                smart_wallets=payload.get("smart_wallet_count"),
            )
            return False

        if mb is None or mb < min_mb:
            logger.info(
                "alerter.gate_blocked",
                mint=mint,
                reason="meaningful_buyers_below_min",
                score=score_f,
                meaningful_buyers=mb,
                min_meaningful=min_mb,
                early_buyers=payload.get("early_buyer_count"),
            )
            return False

        logger.info(
            "alerter.gate_pass",
            mint=mint,
            score=score_f,
            min_score=min_score,
            meaningful_buyers=mb,
            min_meaningful=min_mb,
            entity_launches=payload.get("entity_launch_count"),
            smart_wallets=payload.get("smart_wallet_count"),
        )
        return True

    def _copy_block(self, payload: dict[str, Any]) -> str:
        """Plain-text block optimized for mobile copy → Axiom."""
        mint = payload.get("mint", "?")
        name = payload.get("name") or ""
        symbol = payload.get("symbol") or ""
        score = payload.get("stinky_score")
        vol = payload.get("volume_m5_usd")
        label = " · ".join(x for x in [str(name), str(symbol)] if x) or "Runner"
        lines = [
            f"**STINKY ALERT · {label}**",
            f"CA: `{mint}`",
        ]
        if score is not None:
            lines.append(f"Score: **{float(score):.0f}**")
        if vol is not None:
            lines.append(f"5m vol: **${float(vol):,.0f}**")
        lines.append(f"Axiom: https://axiom.trade/t/{mint}")
        return "\n".join(lines)

    def _build_embed(self, payload: dict[str, Any]) -> discord.Embed:
        mint = payload.get("mint", "?")
        vol = payload.get("volume_m5_usd")
        liq = payload.get("liquidity_usd")
        pool = payload.get("pool")
        price = payload.get("price_usd")
        creator = payload.get("creator")
        name = payload.get("name")
        symbol = payload.get("symbol")

        title = "HIGH-POTENTIAL RUNNER"
        if name or symbol:
            label = " · ".join(x for x in [name, symbol] if x)
            title = f"🚀 {label}"

        embed = discord.Embed(
            title=title,
            description=(
                "**Out of migration** · volume gate cleared · quality gate passed.\n"
                "Paste the **CA** below into Axiom."
            ),
            color=0x00C853,
        )
        if name:
            embed.add_field(name="Name", value=str(name), inline=True)
        if symbol:
            embed.add_field(name="Ticker", value=f"**{symbol}**", inline=True)

        # CA first — most important field for trading
        embed.add_field(
            name="CA (copy)",
            value=f"```\n{mint}\n```",
            inline=False,
        )

        if vol is not None:
            embed.add_field(name="5m Volume", value=f"**${float(vol):,.0f}**", inline=True)
        if liq is not None:
            embed.add_field(name="Liquidity", value=f"${float(liq):,.0f}", inline=True)
        if price is not None:
            embed.add_field(name="Price", value=f"${price}", inline=True)

        score = payload.get("stinky_score")
        conf = payload.get("confidence")
        if score is not None:
            conf_s = f"{float(conf)*100:.0f}%" if conf is not None else "—"
            embed.add_field(
                name="Stinky Score",
                value=f"**{float(score):.0f}/100** · conf {conf_s}",
                inline=True,
            )

        smart_n = payload.get("smart_wallet_count")
        early_n = payload.get("early_buyer_count")
        meaningful_n = payload.get("meaningful_buyer_count")
        avg_hit = payload.get("smart_avg_hit_rate")
        avg_ret = payload.get("smart_avg_return_pct")
        success_n = payload.get("success_wallet_count")
        avg_success = payload.get("avg_early_success_rate")
        mega_n = payload.get("mega_hunter_count")
        if smart_n is not None or early_n is not None or meaningful_n is not None:
            extra = ""
            if avg_hit is not None:
                extra += f"\nHit rate ~{float(avg_hit)*100:.0f}%"
            if avg_ret is not None:
                extra += f" · avg ret {float(avg_ret):+.0f}%"
            embed.add_field(
                name="Early / smart money",
                value=(
                    f"**{int(meaningful_n or 0)}** meaningful · "
                    f"**{int(smart_n or 0)}** tracked smart · "
                    f"{int(early_n or 0)} early{extra}"
                ),
                inline=False,
            )

        if success_n is not None or mega_n is not None or avg_success is not None:
            bits = []
            if success_n is not None:
                bits.append(f"**{int(success_n)}** early buyers with prior runner labels")
            if avg_success is not None:
                try:
                    sr = float(avg_success)
                    if sr > 1.0:
                        sr = sr / 100.0
                    bits.append(f"avg early success **{sr*100:.0f}%**")
                except (TypeError, ValueError):
                    pass
            if mega_n is not None and int(mega_n) > 0:
                bits.append(f"**{int(mega_n)}** prior mega_runner hunters")
            if bits:
                embed.add_field(
                    name="Success book (measured)",
                    value=" · ".join(bits),
                    inline=False,
                )

        top = payload.get("smart_top_wallets") or []
        if isinstance(top, list) and top:
            lines = []
            for item in top[:5]:
                if not isinstance(item, dict):
                    continue
                w = str(item.get("wallet") or "")
                short = f"{w[:6]}…{w[-4:]}" if len(w) > 12 else w
                rank = item.get("rank")
                esr = item.get("early_success_rate")
                extra = ""
                if esr is not None:
                    try:
                        v = float(esr)
                        if v > 1.0:
                            v = v / 100.0
                        extra = f" · succ {v*100:.0f}%"
                    except (TypeError, ValueError):
                        pass
                lines.append(f"`{short}` · rank {rank}{extra}")
            if lines:
                embed.add_field(
                    name="Top early wallets",
                    value="\n".join(lines),
                    inline=False,
                )

        if creator:
            embed.add_field(name="Creator", value=f"`{creator}`", inline=False)
        if pool:
            embed.add_field(name="Pool", value=f"`{pool}`", inline=False)

        elc = payload.get("entity_launch_count")
        ewc = payload.get("entity_wallet_count")
        if elc is not None or ewc is not None:
            risk = "elevated" if int(elc or 0) >= 20 else "normal"
            if int(elc or 0) >= 50:
                risk = "HIGH SERIAL"
            embed.add_field(
                name="Developer entity",
                value=(
                    f"Launches **{int(elc or 0)}** · "
                    f"Wallets **{int(ewc or 1)}** · risk **{risk}**"
                ),
                inline=False,
            )

        explanation = payload.get("score_explanation") or []
        if isinstance(explanation, list) and explanation:
            lines = []
            for item in explanation[:8]:
                if not isinstance(item, dict):
                    continue
                delta = item.get("delta", 0)
                reason = item.get("reason", "")
                sign = "+" if float(delta) >= 0 else ""
                lines.append(f"`{sign}{delta}` {reason}")
            if lines:
                embed.add_field(name="Why this score", value="\n".join(lines), inline=False)

        embed.add_field(
            name="Open",
            value=(
                f"[Axiom](https://axiom.trade/t/{mint}) · "
                f"[DexScreener](https://dexscreener.com/solana/{mint}) · "
                f"[Solscan](https://solscan.io/token/{mint})"
            ),
            inline=False,
        )
        model = payload.get("score_model") or "score-v0.5"
        embed.set_footer(
            text=(
                f"Stinky OS · {model} · score≥{settings.alert_min_score:.0f} · "
                f"≥{settings.alert_min_meaningful_buyers} meaningful · migration only"
            )
        )
        return embed

    async def _dm_subscribers(self, payload: dict[str, Any]) -> None:
        mint = payload.get("mint", "?")
        vol = payload.get("volume_m5_usd")
        embed = self._build_embed(payload)
        copy_txt = self._copy_block(payload)

        channel_posted = False
        channel_id = settings.discord_alert_channel_id
        if channel_id:
            try:
                channel = self._bot.get_channel(channel_id)
                if channel is None:
                    channel = await self._bot.fetch_channel(channel_id)
                if channel is not None:
                    await channel.send(content=copy_txt, embed=embed)
                    channel_posted = True
                    logger.info("alerter.channel_posted", channel_id=channel_id, mint=mint)
            except Exception as exc:
                logger.warning("alerter.channel_failed", channel_id=channel_id, error=str(exc))

        subs = await self._store.list_subscribers()
        logger.info(
            "alerter.dispatch",
            mint=mint,
            subscribers=len(subs),
            volume_m5=vol,
            score=payload.get("stinky_score"),
        )
        dm_ok = 0
        for uid in subs:
            try:
                user = await self._bot.fetch_user(uid)
                # Text first (easy copy on phone) + full embed
                await user.send(content=copy_txt, embed=embed)
                dm_ok += 1
            except Exception as exc:
                logger.warning("alerter.dm_failed", user_id=uid, error=str(exc))

        # Durable record for outcome/precision measurement (ADR-002 derived state)
        try:
            alert_id = await self._store.log_alert(
                mint=str(mint),
                score=float(payload["stinky_score"]) if payload.get("stinky_score") is not None else None,
                confidence=float(payload["confidence"]) if payload.get("confidence") is not None else None,
                volume_m5_usd=float(vol) if vol is not None else None,
                meaningful_buyers=(
                    int(payload["meaningful_buyer_count"])
                    if payload.get("meaningful_buyer_count") is not None
                    else None
                ),
                entity_launch_count=(
                    int(payload["entity_launch_count"])
                    if payload.get("entity_launch_count") is not None
                    else None
                ),
                score_model=str(payload.get("score_model") or "") or None,
                name=str(payload["name"]) if payload.get("name") else None,
                symbol=str(payload["symbol"]) if payload.get("symbol") else None,
                deployer=str(payload.get("creator") or payload.get("deployer") or "") or None,
                dm_sent=dm_ok > 0,
                channel_posted=channel_posted,
                payload=payload,
            )
            logger.info(
                "alerter.logged",
                mint=mint,
                alert_id=alert_id,
                dm_ok=dm_ok,
                channel_posted=channel_posted,
            )
        except Exception as exc:
            logger.warning("alerter.log_alert_error", mint=mint, error=str(exc))

    async def _already_alerted(self, mint: str) -> bool:
        """Memory + Redis (48h) + alert_log — one DM per mint."""
        if mint in self._alerted_mints:
            return True
        assert self._redis is not None
        try:
            key = f"stinky:alerted:{mint}"
            if await self._redis.exists(key):
                self._alerted_mints.add(mint)
                return True
        except Exception as exc:
            logger.debug("alerter.dedupe_redis_failed", error=str(exc))
        try:
            recent = await self._store.recent_alert_mints(hours=48)
            if mint in recent:
                self._alerted_mints.add(mint)
                return True
        except Exception as exc:
            logger.debug("alerter.dedupe_db_failed", error=str(exc))
        return False

    async def _mark_alerted(self, mint: str) -> None:
        """Remember mint for 48h so we never re-DM the same CA."""
        self._alerted_mints.add(mint)
        assert self._redis is not None
        try:
            key = f"stinky:alerted:{mint}"
            await self._redis.set(key, "1", ex=48 * 3600)
        except Exception as exc:
            logger.debug("alerter.mark_redis_failed", error=str(exc), mint=mint)
