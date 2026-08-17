"""Stinky OS Discord bot – slash commands + high-potential DM alerts."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands
import structlog

from discord_bot.alerter import AlertDispatcher
from discord_bot.config import settings
from discord_bot.dex import fetch_token_metrics
from discord_bot.store import Store

logger = structlog.get_logger(__name__)


def _fmt_ts(v) -> str:
    if v is None:
        return "—"
    if hasattr(v, "isoformat"):
        return v.isoformat().replace("+00:00", "Z")
    return str(v)


def _fmt_usd(v) -> str:
    if v is None:
        return "—"
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return str(v)


class StinkyBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = False
        super().__init__(command_prefix="!", intents=intents)
        self.store = Store()
        self.alerter: AlertDispatcher | None = None

    async def setup_hook(self) -> None:
        await self.store.ensure_schema()
        self.tree.add_command(intel)
        self.tree.add_command(alerts_group)
        if settings.discord_guild_id:
            guild = discord.Object(id=settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("discord.commands_synced", guild=settings.discord_guild_id)
        else:
            await self.tree.sync()
            logger.info("discord.commands_synced_global")

        self.alerter = AlertDispatcher(self, self.store)
        await self.alerter.start()

    async def on_ready(self) -> None:
        logger.info("discord.ready", user=str(self.user), id=self.user.id if self.user else None)

    async def close(self) -> None:
        if self.alerter:
            await self.alerter.stop()
        await self.store.close()
        await super().close()


# ── Command groups ──────────────────────────────────────────────

intel = app_commands.Group(name="stinky", description="Stinky OS intelligence commands")
alerts_group = app_commands.Group(name="alerts", description="High-potential migration alert controls")


@alerts_group.command(name="subscribe", description="DM me only high-potential runners (migration + $25k 5m vol)")
async def subscribe(interaction: discord.Interaction) -> None:
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    await bot.store.subscribe(interaction.user.id, str(interaction.user))
    embed = discord.Embed(
        title="Subscribed",
        description=(
            "You will receive **DMs only** when a coin:\n"
            "1. Just **migrated** out of bond (not a create)\n"
            "2. Hits **≥ $25,000** in 5‑minute volume\n\n"
            "Quiet migrations and pre-bond launches are ignored."
        ),
        color=0x00C853,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@alerts_group.command(name="unsubscribe", description="Stop high-potential DMs")
async def unsubscribe(interaction: discord.Interaction) -> None:
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    await bot.store.unsubscribe(interaction.user.id)
    await interaction.response.send_message(
        "Unsubscribed. No more runner DMs until you `/alerts subscribe` again.",
        ephemeral=True,
    )


@alerts_group.command(name="status", description="Your alert subscription + bot thresholds")
async def alert_status(interaction: discord.Interaction) -> None:
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    sub = await bot.store.is_subscribed(interaction.user.id)
    embed = discord.Embed(title="Alert status", color=0x2196F3)
    embed.add_field(name="Subscribed", value="Yes" if sub else "No", inline=True)
    embed.add_field(
        name="Volume gate",
        value=f"${settings.volume_threshold_usd:,.0f} / 5m",
        inline=True,
    )
    embed.add_field(
        name="Triggers on",
        value="Migration + volume only (never Create)",
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@intel.command(name="help", description="What Stinky OS Discord can do")
async def help_cmd(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="Stinky OS · Commands",
        description=(
            "Intelligence layer for Solana **post-migration** runners.\n"
            "We do **not** spam creates or dead graduates."
        ),
        color=0x9C27B0,
    )
    embed.add_field(
        name="Alerts",
        value=(
            "`/alerts subscribe` — DM high-potential only\n"
            "`/alerts unsubscribe`\n"
            "`/alerts status`\n"
            "`/alerts recent` — last candidates"
        ),
        inline=False,
    )
    embed.add_field(
        name="Markets",
        value=(
            "`/stinky market mint:` — launch / migration / volume log\n"
            "`/stinky volume mint:` — live DexScreener 5m/1h/24h\n"
            "`/stinky recent_migrations`\n"
            "`/stinky recent_launches`"
        ),
        inline=False,
    )
    embed.add_field(
        name="Wallets / Smart Money",
        value=(
            "`/stinky wallets` — top smart wallets (Smart Score)\n"
            "`/stinky success` — early buyers by measured runner labels\n"
            "`/stinky wallet address:` — score + performance + entity\n"
            "`/stinky buyers mint:` — first 20 post-migration buyers\n"
            "`/stinky migrations` — recent graduations + buyer capture"
        ),
        inline=False,
    )
    embed.add_field(
        name="Outcomes",
        value=(
            "`/stinky precision` — runner rate on gated alerts\n"
            "`/stinky outcomes` — recent alert_log labels"
        ),
        inline=False,
    )
    embed.add_field(
        name="System",
        value="`/stinky status` — bot + pipeline health",
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@intel.command(name="status", description="Pipeline health and thresholds")
async def system_status(interaction: discord.Interaction) -> None:
    embed = discord.Embed(title="Stinky OS status", color=0x607D8B)
    embed.add_field(
        name="Modes",
        value="create · migration · volume_gate · collector · discord",
        inline=False,
    )
    embed.add_field(name="Volume threshold", value=f"${settings.volume_threshold_usd:,.0f} / 5m", inline=True)
    embed.add_field(name="Environment", value=settings.environment, inline=True)
    embed.add_field(
        name="Alert rule",
        value="`token.migrated` + volume ≥ threshold → `alert.candidate` → DM subscribers",
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@intel.command(name="market", description="Logged intel for a mint (launch, migration, volume)")
@app_commands.describe(mint="Token mint address")
async def market(interaction: discord.Interaction, mint: str) -> None:
    await interaction.response.defer(ephemeral=True)
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    mint = mint.strip()
    data = await bot.store.market_by_mint(mint)
    live = await fetch_token_metrics(mint)

    embed = discord.Embed(title="Market intel", color=0xFF9800)
    embed.add_field(name="Mint", value=f"`{mint}`", inline=False)

    if data["launch"]:
        p = data["launch"]["payload"] or {}
        embed.add_field(
            name="Launch",
            value=(
                f"Name: {p.get('name') or '—'} ({p.get('symbol') or '—'})\n"
                f"Deployer: `{p.get('deployer') or '—'}`\n"
                f"At: {_fmt_ts(data['launch']['occurred_at'])}"
            ),
            inline=False,
        )
    if data["migrated"]:
        p = data["migrated"]["payload"] or {}
        embed.add_field(
            name="Migration",
            value=(
                f"Pool: `{p.get('pool') or '—'}`\n"
                f"At: {_fmt_ts(data['migrated']['occurred_at'])}"
            ),
            inline=False,
        )
    if data["volume"]:
        p = data["volume"]["payload"] or {}
        embed.add_field(
            name="Volume gate",
            value=f"5m: {_fmt_usd(p.get('volume_m5_usd'))} · Liq: {_fmt_usd(p.get('liquidity_usd'))}",
            inline=False,
        )
    if data["alert"]:
        embed.add_field(name="Alert candidate", value="Yes — high-potential path fired", inline=False)

    if live:
        embed.add_field(
            name="Live (DexScreener)",
            value=(
                f"{live.get('name') or ''} ({live.get('symbol') or ''})\n"
                f"5m vol: {_fmt_usd(live.get('volume_m5'))} · "
                f"1h: {_fmt_usd(live.get('volume_h1'))} · "
                f"Liq: {_fmt_usd(live.get('liquidity_usd'))}\n"
                f"Price: ${live.get('price_usd') or '—'} · DEX: {live.get('dex_id') or '—'}"
            ),
            inline=False,
        )
        if live.get("url"):
            embed.add_field(name="Chart", value=live["url"], inline=False)

    if data["event_count"] == 0 and not live:
        embed.description = "No stored events and no DexScreener pair yet."

    await interaction.followup.send(embed=embed, ephemeral=True)


@intel.command(name="volume", description="Live 5m / 1h / 24h volume and liquidity")
@app_commands.describe(mint="Token mint address")
async def volume_cmd(interaction: discord.Interaction, mint: str) -> None:
    await interaction.response.defer(ephemeral=True)
    live = await fetch_token_metrics(mint.strip())
    if not live:
        await interaction.followup.send("No DexScreener data for that mint yet.", ephemeral=True)
        return
    embed = discord.Embed(
        title=f"{live.get('name') or mint} · volume",
        color=0x00BCD4,
    )
    embed.add_field(name="5m", value=_fmt_usd(live.get("volume_m5")), inline=True)
    embed.add_field(name="1h", value=_fmt_usd(live.get("volume_h1")), inline=True)
    embed.add_field(name="24h", value=_fmt_usd(live.get("volume_h24")), inline=True)
    embed.add_field(name="Liquidity", value=_fmt_usd(live.get("liquidity_usd")), inline=True)
    embed.add_field(name="Price", value=f"${live.get('price_usd') or '—'}", inline=True)
    embed.add_field(name="DEX", value=str(live.get("dex_id") or "—"), inline=True)
    if live.get("url"):
        embed.add_field(name="Chart", value=live["url"], inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)


@intel.command(name="wallets", description="Top smart wallets by Smart Score")
@app_commands.describe(limit="How many (1-25)")
async def wallets_cmd(
    interaction: discord.Interaction, limit: app_commands.Range[int, 1, 25] = 10
) -> None:
    await interaction.response.defer(ephemeral=True)
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    rows = await bot.store.top_smart_wallets(limit=limit)
    if not rows:
        await interaction.followup.send(
            "No smart-wallet data yet.\n"
            "Needs: migration → collector → first 20 buyers.\n"
            "Leave Collector running; re-check after graduations.",
            ephemeral=True,
        )
        return
    embed = discord.Embed(
        title="Smart wallets",
        description="Ranked by **Smart Score** (early buys · hit rate · returns · PnL)",
        color=0x00BCD4,
    )
    for i, r in enumerate(rows[:15], start=1):
        w = r.get("wallet") or "?"
        short = f"{w[:6]}…{w[-4:]}" if len(w) > 12 else w
        score = r.get("smart_score")
        score_s = f"{float(score):.0f}" if score is not None else "—"
        hit = r.get("hit_rate")
        hit_s = f"{float(hit)*100:.0f}%" if hit is not None else "—"
        avg = r.get("avg_return_pct")
        avg_s = f"{float(avg):+.0f}%" if avg is not None else "—"
        early = r.get("early_buy_count") or 0
        tokens = r.get("tokens_purchased") or 0
        embed.add_field(
            name=f"#{i}  {short}  ·  score **{score_s}**",
            value=(
                f"`{w}`\n"
                f"Early **{early}** · Tokens **{tokens}** · Hit {hit_s} · Avg {avg_s}\n"
                f"PnL ${float(r.get('realized_pnl_usd') or 0):,.0f}"
            ),
            inline=False,
        )
    embed.set_footer(text="Smart Score v1 · syncs early counts from migration_buyers")
    await interaction.followup.send(embed=embed, ephemeral=True)


@intel.command(
    name="patterns",
    description="Wallets that early-buy multiple migrations (repeat edge)",
)
@app_commands.describe(
    min_mints="Minimum distinct migrations (default 2)",
    limit="How many wallets (1-25)",
)
async def patterns_cmd(
    interaction: discord.Interaction,
    min_mints: app_commands.Range[int, 2, 20] = 2,
    limit: app_commands.Range[int, 1, 25] = 10,
) -> None:
    await interaction.response.defer(ephemeral=True)
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    rows = await bot.store.early_buyer_patterns(min_mints=min_mints, limit=limit)
    if not rows:
        await interaction.followup.send(
            "No repeat early-buyer patterns yet.\n"
            "Needs several migrations with collector buyers logged.",
            ephemeral=True,
        )
        return
    embed = discord.Embed(
        title="Early-buyer patterns",
        description=(
            f"Wallets early on **≥ {min_mints}** migrations "
            "(first ranks · not the pool)"
        ),
        color=0xFF9800,
    )
    for i, r in enumerate(rows, start=1):
        w = r.get("wallet") or "?"
        short = f"{w[:6]}…{w[-4:]}" if len(w) > 12 else w
        mc = r.get("migration_count") or 0
        best = r.get("best_rank")
        avg = r.get("avg_rank")
        sol = r.get("total_sol_spent")
        avg_s = f"{float(avg):.1f}" if avg is not None else "—"
        sol_s = f"{float(sol):.2f}" if sol is not None else "—"
        embed.add_field(
            name=f"#{i}  {short}  ·  **{mc}** mints",
            value=(
                f"`{w}`\n"
                f"Best rank **{best}** · Avg rank {avg_s} · "
                f"SOL spent ~{sol_s}"
            ),
            inline=False,
        )
    embed.set_footer(text="Pattern discovery lite · Postgres migration_buyers")
    await interaction.followup.send(embed=embed, ephemeral=True)


@intel.command(name="buyers", description="First post-migration buyers for a mint")
@app_commands.describe(mint="Token mint address")
async def buyers_cmd(interaction: discord.Interaction, mint: str) -> None:
    await interaction.response.defer(ephemeral=True)
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    mint = mint.strip()
    rows = await bot.store.migration_buyers(mint, limit=20)
    if not rows:
        await interaction.followup.send(
            "No early buyers logged for that mint yet (need migration + collector).",
            ephemeral=True,
        )
        return
    embed = discord.Embed(title=f"Early buyers · `{mint[:8]}…`", color=0x8BC34A)
    for r in rows:
        rank = r.get("rank")
        w = r.get("wallet") or "?"
        sol = r.get("sol_spent")
        sol_s = f"{float(sol):.3f} SOL" if sol is not None else "—"
        embed.add_field(
            name=f"#{rank}",
            value=f"`{w}`\n{sol_s} · {_fmt_ts(r.get('bought_at'))}",
            inline=False,
        )
    await interaction.followup.send(embed=embed, ephemeral=True)


@intel.command(name="wallet", description="Wallet performance + deployer history")
@app_commands.describe(address="Wallet address")
async def wallet_cmd(interaction: discord.Interaction, address: str) -> None:
    await interaction.response.defer(ephemeral=True)
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    address = address.strip()
    stats = await bot.store.deployer_stats(address)
    perf = await bot.store.wallet_performance(address)
    entity = await bot.store.entity_for_wallet(address)

    embed = discord.Embed(title="Wallet intel", color=0x3F51B5)
    embed.add_field(name="Address", value=f"`{address}`", inline=False)

    if perf:
        score = perf.get("smart_score")
        if score is not None:
            embed.add_field(name="Smart Score", value=f"**{float(score):.0f}**/100", inline=True)
        hit = perf.get("hit_rate")
        hit_s = f"{float(hit)*100:.0f}%" if hit is not None else "—"
        embed.add_field(name="Early buys", value=str(perf.get("early_buy_count") or 0), inline=True)
        embed.add_field(name="Tokens bought", value=str(perf.get("tokens_purchased") or 0), inline=True)
        embed.add_field(name="Hit rate", value=hit_s, inline=True)
        avg = perf.get("avg_return_pct")
        med = perf.get("median_return_pct")
        mx = perf.get("max_return_pct")
        if avg is not None:
            med_s = f"{float(med):+.1f}%" if med is not None else "—"
            mx_s = f"{float(mx):+.1f}%" if mx is not None else "—"
            embed.add_field(
                name="Returns",
                value=f"Avg {float(avg):+.1f}% · Med {med_s} · Max {mx_s}",
                inline=False,
            )
        embed.add_field(
            name="Realized PnL",
            value=f"${float(perf.get('realized_pnl_usd') or 0):,.2f} · "
            f"{float(perf.get('realized_pnl_sol') or 0):+.3f} SOL",
            inline=False,
        )
        why = perf.get("score_explanation") or []
        if isinstance(why, list) and why:
            lines = []
            for item in why[:6]:
                if not isinstance(item, dict):
                    continue
                d = item.get("delta", 0)
                sign = "+" if float(d) >= 0 else ""
                lines.append(f"{sign}{d} {item.get('reason', '')}")
            if lines:
                embed.add_field(name="Why", value="\n".join(lines), inline=False)
        ms = perf.get("milestones_hit") or {}
        if isinstance(ms, dict) and ms:
            embed.add_field(
                name="Milestones",
                value=" · ".join(f"{k}:{v}" for k, v in ms.items()),
                inline=False,
            )
    else:
        embed.add_field(
            name="Performance",
            value="No smart-money row yet (collector after migrations).",
            inline=False,
        )

    if entity:
        embed.add_field(
            name="Entity",
            value=(
                f"{entity.get('display_label') or 'operator'} · "
                f"launches {entity.get('launch_count') or 0} · "
                f"wallets {entity.get('wallet_count') or 1} · "
                f"conf {float(entity.get('confidence') or 0)*100:.0f}%"
            ),
            inline=False,
        )

    embed.add_field(name="Stored launches (as deployer)", value=str(stats["launches"]), inline=True)
    embed.add_field(name="First seen", value=_fmt_ts(stats["first_seen"]), inline=True)
    embed.add_field(name="Last seen", value=_fmt_ts(stats["last_seen"]), inline=True)
    if stats["recent"]:
        lines = []
        for r in stats["recent"][:6]:
            lines.append(
                f"• `{r.get('mint') or '?'}` {r.get('name') or ''} · {_fmt_ts(r.get('occurred_at'))}"
            )
        embed.add_field(name="Recent mints launched", value="\n".join(lines) or "—", inline=False)
    embed.set_footer(text="Smart Score v1 · Stinky OS")
    await interaction.followup.send(embed=embed, ephemeral=True)


@intel.command(name="migrations", description="Recent token migrations + buyer capture status")
@app_commands.describe(limit="How many (1-15)")
async def migrations_cmd(
    interaction: discord.Interaction, limit: app_commands.Range[int, 1, 15] = 8
) -> None:
    await interaction.response.defer(ephemeral=True)
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    rows = await bot.store.recent_migrated_mints(limit=limit)
    if not rows:
        await interaction.followup.send(
            "No token.migrated events stored yet.",
            ephemeral=True,
        )
        return
    embed = discord.Embed(title="Recent migrations", color=0xFF9800)
    for r in rows:
        mint = r.get("mint") or "?"
        short = f"{mint[:8]}…" if len(mint) > 10 else mint
        buyers = r.get("buyer_count") or 0
        embed.add_field(
            name=f"{short} · buyers {buyers}",
            value=(
                f"`{mint}`\n"
                f"Creator `{r.get('creator') or '—'}`\n"
                f"{_fmt_ts(r.get('occurred_at'))}"
            ),
            inline=False,
        )
    embed.set_footer(text="Buyer count from migration_buyers (collector)")
    await interaction.followup.send(embed=embed, ephemeral=True)


@intel.command(name="entities", description="Top operator entities (wallet clusters)")
@app_commands.describe(limit="How many (1-25)")
async def entities_cmd(
    interaction: discord.Interaction, limit: app_commands.Range[int, 1, 25] = 10
) -> None:
    await interaction.response.defer(ephemeral=True)
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    rows = await bot.store.top_entities(limit=limit)
    if not rows:
        await interaction.followup.send(
            "No entities yet. Run entity-resolver after launches/migrations.",
            ephemeral=True,
        )
        return
    embed = discord.Embed(title="Entities", color=0x673AB7)
    for r in rows[:15]:
        pw = r.get("primary_wallet") or "?"
        short = f"{pw[:6]}…{pw[-4:]}" if len(pw) > 12 else pw
        embed.add_field(
            name=f"{r.get('display_label') or short} · {r.get('entity_type')}",
            value=(
                f"`{pw}`\n"
                f"Wallets {r.get('wallet_count')} · Launches {r.get('launch_count')} · "
                f"Early buys {r.get('early_buy_count')} · "
                f"Conf {float(r.get('confidence') or 0):.0%}"
            ),
            inline=False,
        )
    await interaction.followup.send(embed=embed, ephemeral=True)


@intel.command(name="entity", description="Entity linked to a wallet")
@app_commands.describe(wallet="Wallet address")
async def entity_cmd(interaction: discord.Interaction, wallet: str) -> None:
    await interaction.response.defer(ephemeral=True)
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    wallet = wallet.strip()
    ent = await bot.store.entity_for_wallet(wallet)
    if not ent:
        await interaction.followup.send(
            "No entity linked to that wallet yet.", ephemeral=True
        )
        return
    members = await bot.store.entity_wallets(str(ent["entity_id"]))
    embed = discord.Embed(
        title=f"Entity · {ent.get('display_label') or wallet[:8]}",
        color=0x7E57C2,
    )
    embed.add_field(name="Entity ID", value=f"`{ent['entity_id']}`", inline=False)
    embed.add_field(name="Type", value=str(ent.get("entity_type")), inline=True)
    embed.add_field(
        name="Confidence",
        value=f"{float(ent.get('confidence') or 0):.0%}",
        inline=True,
    )
    embed.add_field(
        name="Stats",
        value=(
            f"Wallets {ent.get('wallet_count')} · "
            f"Launches {ent.get('launch_count')} · "
            f"Early buys {ent.get('early_buy_count')}"
        ),
        inline=False,
    )
    if members:
        lines = [
            f"• `{m['wallet']}` · {m.get('role')} · {m.get('link_reason')}"
            for m in members[:12]
        ]
        embed.add_field(name="Linked wallets", value="\n".join(lines), inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)


@intel.command(name="recent_migrations", description="Latest migrations we logged")
@app_commands.describe(limit="How many (1-25)")
async def recent_migrations(interaction: discord.Interaction, limit: app_commands.Range[int, 1, 25] = 10) -> None:
    await interaction.response.defer(ephemeral=True)
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    rows = await bot.store.recent_events("token.migrated", limit=limit)
    if not rows:
        await interaction.followup.send("No migrations logged yet.", ephemeral=True)
        return
    embed = discord.Embed(title="Recent migrations", color=0x4CAF50)
    for r in rows[:15]:
        p = r["payload"] or {}
        embed.add_field(
            name=_fmt_ts(r["occurred_at"]),
            value=f"`{p.get('mint')}`\nPool: `{p.get('pool') or '—'}`",
            inline=False,
        )
    await interaction.followup.send(embed=embed, ephemeral=True)


@intel.command(name="recent_launches", description="Latest creates we logged")
@app_commands.describe(limit="How many (1-25)")
async def recent_launches(interaction: discord.Interaction, limit: app_commands.Range[int, 1, 25] = 10) -> None:
    await interaction.response.defer(ephemeral=True)
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    rows = await bot.store.recent_events("token.launch", limit=limit)
    if not rows:
        await interaction.followup.send("No launches logged yet.", ephemeral=True)
        return
    embed = discord.Embed(title="Recent launches", color=0xFFC107)
    for r in rows[:15]:
        p = r["payload"] or {}
        name = p.get("name") or "—"
        embed.add_field(
            name=f"{name} ({p.get('symbol') or '—'})",
            value=f"`{p.get('mint')}`\nDeployer: `{p.get('deployer') or '—'}`",
            inline=False,
        )
    await interaction.followup.send(embed=embed, ephemeral=True)


@alerts_group.command(name="recent", description="Latest high-potential alert candidates")
@app_commands.describe(limit="How many (1-25)")
async def recent_alerts(interaction: discord.Interaction, limit: app_commands.Range[int, 1, 25] = 10) -> None:
    await interaction.response.defer(ephemeral=True)
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    rows = await bot.store.recent_events("alert.candidate", limit=limit)
    if not rows:
        await interaction.followup.send(
            "No alert candidates yet. They appear when migration + $25k 5m volume both hit.",
            ephemeral=True,
        )
        return
    embed = discord.Embed(title="High-potential alerts", color=0xE91E63)
    for r in rows[:15]:
        p = r["payload"] or {}
        embed.add_field(
            name=_fmt_ts(r["occurred_at"]),
            value=(
                f"`{p.get('mint')}`\n"
                f"5m vol: {_fmt_usd(p.get('volume_m5_usd'))} · "
                f"Liq: {_fmt_usd(p.get('liquidity_usd'))}"
            ),
            inline=False,
        )
    await interaction.followup.send(embed=embed, ephemeral=True)


@intel.command(name="threshold", description="Show the volume gate used for DMs")
async def threshold_cmd(interaction: discord.Interaction) -> None:
    embed = discord.Embed(title="Volume gate", color=0x795548)
    embed.add_field(name="Minimum 5m volume", value=f"${settings.volume_threshold_usd:,.0f}", inline=False)
    embed.add_field(
        name="Logic",
        value="Migration detected → poll DexScreener → if 5m vol ≥ gate → `alert.candidate` → DM subscribers",
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@intel.command(name="precision", description="Runner rate on gated alerts we DM'd")
async def precision_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    data = await bot.store.alert_precision_summary(limit=80)
    if not data.get("available"):
        await interaction.followup.send(
            f"Precision unavailable: {data.get('message') or 'no alert_log yet'}",
            ephemeral=True,
        )
        return
    total = int(data.get("total") or 0)
    rate = data.get("runner_rate")
    counts = data.get("counts") or {}
    rate_s = f"{rate*100:.0f}%" if rate is not None else "—"
    lines = [f"**{lab}** {n}" for lab, n in sorted(counts.items(), key=lambda x: -x[1])]
    embed = discord.Embed(
        title="Alert precision",
        description=(
            f"Measured from `alert_log` + `alert_outcomes` (not invented).\n"
            f"**Runner rate:** {rate_s} · **Alerts:** {total}"
        ),
        color=0x00C853,
    )
    if lines:
        embed.add_field(name="Labels", value="\n".join(lines), inline=False)
    else:
        embed.add_field(
            name="Labels",
            value="No labeled rows yet — outcomes fill after market_snapshots exist.",
            inline=False,
        )
    embed.set_footer(text="Also on Terminal → Command Center / Backtest")
    await interaction.followup.send(embed=embed, ephemeral=True)


@intel.command(name="outcomes", description="Recent gated alerts + measured labels")
@app_commands.describe(limit="How many (1-20)")
async def outcomes_cmd(
    interaction: discord.Interaction, limit: app_commands.Range[int, 1, 20] = 10
) -> None:
    await interaction.response.defer(ephemeral=True)
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    rows = await bot.store.recent_alert_log(limit=limit)
    if not rows:
        await interaction.followup.send(
            "No rows in alert_log yet. After a gated DM, they appear here.",
            ephemeral=True,
        )
        return
    embed = discord.Embed(title="Alert outcomes", color=0xE91E63)
    for r in rows[:15]:
        mint = str(r.get("mint") or "?")
        short = f"{mint[:6]}…{mint[-4:]}" if len(mint) > 12 else mint
        label = r.get("label") or "unknown"
        score = r.get("score")
        score_s = f"{float(score):.0f}" if score is not None else "—"
        name = r.get("symbol") or r.get("name") or short
        embed.add_field(
            name=f"{name} · {label}",
            value=(
                f"`{mint}`\n"
                f"Score {score_s} · 5m {_fmt_usd(r.get('volume_m5_usd'))} · "
                f"DM {'yes' if r.get('dm_sent') else 'no'}"
            ),
            inline=False,
        )
    await interaction.followup.send(embed=embed, ephemeral=True)


@intel.command(
    name="success",
    description="Early buyers ranked by measured success on labeled runners",
)
@app_commands.describe(limit="How many (1-25)")
async def success_cmd(
    interaction: discord.Interaction, limit: app_commands.Range[int, 1, 25] = 12
) -> None:
    await interaction.response.defer(ephemeral=True)
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    rows = await bot.store.top_success_wallets(limit=limit)
    if not rows:
        await interaction.followup.send(
            "No wallet_early_success rows yet. Run: `stinky-collector learn-success`",
            ephemeral=True,
        )
        return
    embed = discord.Embed(
        title="Early success (measured labels)",
        description="From token_outcomes → wallet_early_success. Not a tip list.",
        color=0x00BFA5,
    )
    for r in rows[:15]:
        w = str(r.get("wallet") or "?")
        short = f"{w[:6]}…{w[-4:]}" if len(w) > 12 else w
        sr = r.get("success_rate")
        if sr is not None:
            v = float(sr)
            if v > 1.0:
                v = v / 100.0
            sr_s = f"{v*100:.0f}%"
        else:
            sr_s = "—"
        embed.add_field(
            name=f"{short} · success {sr_s}",
            value=(
                f"`{w}`\n"
                f"Sample {r.get('sample_size') or 0} · "
                f"mega {r.get('early_on_mega') or 0} · "
                f"runner {r.get('early_on_runner') or 0} · "
                f"mid {r.get('early_on_mid') or 0} · "
                f"fade {r.get('early_on_fade') or 0}"
            ),
            inline=False,
        )
    embed.set_footer(text="stinky-collector learn-success refreshes this table")
    await interaction.followup.send(embed=embed, ephemeral=True)


@intel.command(name="watch", description="Your saved watchlist (wallets + mints)")
async def watch_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    rows = await bot.store.watchlist_list(limit=20)
    if not rows:
        await interaction.followup.send(
            "Watchlist empty. Use `/stinky watch_add kind:wallet address:...`",
            ephemeral=True,
        )
        return
    embed = discord.Embed(title="Watchlist", color=0x26A69A)
    for r in rows:
        addr = str(r.get("address") or "")
        kind = r.get("kind") or "?"
        note = r.get("note") or ""
        short = f"{addr[:6]}…{addr[-4:]}" if len(addr) > 12 else addr
        embed.add_field(
            name=f"{kind} · {short}",
            value=f"`{addr}`" + (f"\n{note}" if note else ""),
            inline=False,
        )
    await interaction.followup.send(embed=embed, ephemeral=True)


@intel.command(name="watch_add", description="Save a wallet or mint to the watchlist")
@app_commands.describe(kind="wallet or mint", address="Solana address", note="optional note")
@app_commands.choices(
    kind=[
        app_commands.Choice(name="wallet", value="wallet"),
        app_commands.Choice(name="mint", value="mint"),
    ]
)
async def watch_add_cmd(
    interaction: discord.Interaction,
    kind: app_commands.Choice[str],
    address: str,
    note: str | None = None,
) -> None:
    await interaction.response.defer(ephemeral=True)
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    await bot.store.watchlist_add(kind=kind.value, address=address, note=note)
    await interaction.followup.send(
        f"Saved **{kind.value}** `{address.strip()}`", ephemeral=True
    )


@intel.command(name="watch_remove", description="Remove from watchlist")
@app_commands.describe(kind="wallet or mint", address="Solana address")
@app_commands.choices(
    kind=[
        app_commands.Choice(name="wallet", value="wallet"),
        app_commands.Choice(name="mint", value="mint"),
    ]
)
async def watch_remove_cmd(
    interaction: discord.Interaction,
    kind: app_commands.Choice[str],
    address: str,
) -> None:
    await interaction.response.defer(ephemeral=True)
    bot: StinkyBot = interaction.client  # type: ignore[assignment]
    ok = await bot.store.watchlist_remove(kind=kind.value, address=address)
    await interaction.followup.send(
        "Removed." if ok else "Not on list.", ephemeral=True
    )
