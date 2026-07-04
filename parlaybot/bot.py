from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time

import discord
from discord import app_commands
from discord.ext import tasks

from .config import Settings, load_settings
from .daily import DailyDropService
from .odds import OddsClient, OddsError, find_event, format_american
from .persona import PersonaClient
from .storage import BetStore, LeaderboardEntry


LOGGER = logging.getLogger(__name__)


class DegenBot(discord.Client):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.settings = settings
        self.tree = app_commands.CommandTree(self)
        self.store = BetStore(settings.database_path)
        self.odds_client = OddsClient(settings.odds_api_key, settings.bookmakers)
        self.persona_client = PersonaClient(settings.ollama_base_url, settings.ollama_model)
        self.daily_service = DailyDropService(
            odds_client=self.odds_client,
            persona_client=self.persona_client,
            store=self.store,
            sport_key=settings.sport_key,
        )
        self.daily_drop_loop.change_interval(time=time(hour=10, minute=0, tzinfo=settings.timezone))

    async def setup_hook(self) -> None:
        self.store.initialize()
        _register_commands(self)
        if self.settings.discord_guild_id:
            guild = discord.Object(id=self.settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        self.daily_drop_loop.start()

    async def close(self) -> None:
        self.daily_drop_loop.cancel()
        await super().close()

    @tasks.loop(time=time(hour=10, minute=0))
    async def daily_drop_loop(self) -> None:
        if not self.settings.discord_channel_id:
            LOGGER.warning("DISCORD_CHANNEL_ID is not configured; skipping daily drop")
            return
        channel = self.get_channel(self.settings.discord_channel_id)
        if channel is None:
            channel = await self.fetch_channel(self.settings.discord_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            LOGGER.warning("Configured daily-drop channel is not messageable")
            return

        drop = await self.daily_service.build_drop()
        await channel.send(embed=_daily_embed(drop.content))
        self.daily_service.record_drop(drop, self.settings.discord_channel_id)

    @daily_drop_loop.before_loop
    async def before_daily_drop(self) -> None:
        await self.wait_until_ready()


def _register_commands(bot: DegenBot) -> None:
    @bot.tree.command(name="odds", description="Fetch DraftKings/FanDuel consensus odds for a matchup.")
    @app_commands.describe(matchup="Team or matchup to search for")
    async def odds(interaction: discord.Interaction, matchup: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            events = await bot.odds_client.fetch_odds(bot.settings.sport_key)
        except OddsError as exc:
            await interaction.followup.send(f"Odds board is cooked right now: {exc}", ephemeral=True)
            return

        event = find_event(events, matchup)
        if event is None:
            await interaction.followup.send(f"Could not find a matchup for `{matchup}`.", ephemeral=True)
            return

        lines = []
        for outcome in event.outcomes:
            dk = format_american(outcome.prices.get("draftkings"))
            fd = format_american(outcome.prices.get("fanduel"))
            consensus = format_american(outcome.consensus)
            lines.append(f"**{outcome.name}** - DK {dk} | FD {fd} | Consensus {consensus}")
        await interaction.followup.send(f"**{event.matchup}**\n" + "\n".join(lines))

    @bot.tree.command(name="bet", description="Log a fake-dollar bet.")
    @app_commands.describe(amount="Fake dollars wagered", pick="Your pick, e.g. Brazil ML")
    async def bet(interaction: discord.Interaction, amount: float, pick: str) -> None:
        try:
            logged = bot.store.log_bet(
                user_id=interaction.user.id,
                username=interaction.user.display_name,
                amount=amount,
                pick=pick,
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Locked in bet #{logged.id}: ${logged.amount:.2f} on {logged.pick}. "
            "May the gambling gods have mercy on your spreadsheet."
        )

    @bot.tree.command(name="resolve", description="Admin: grade a bet as win, loss, or push.")
    @app_commands.describe(bet_id="Bet ID to resolve", result="win, loss, or push")
    async def resolve(interaction: discord.Interaction, bet_id: int, result: str) -> None:
        if not _can_resolve_bets(interaction):
            await interaction.response.send_message("Admin only. Go win a mod election first.", ephemeral=True)
            return

        result = result.lower().strip()
        try:
            resolved = bot.store.resolve_bet(bet_id, result)
        except (ValueError, KeyError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Bet #{resolved.id} graded {resolved.result}. "
            f"{resolved.username} P&L: ${resolved.profit:.2f}."
        )

    @bot.tree.command(name="leaderboard", description="Show server net-profit rankings.")
    async def leaderboard(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        entries = bot.store.leaderboard()
        if not entries:
            await interaction.followup.send("No bets logged yet. Cowards everywhere.")
            return

        rows = [
            (
                f"**{idx}. {entry.username}** - ${entry.net_profit:.2f} "
                f"({entry.wins}W-{entry.losses}L-{entry.pushes}P, {entry.pending} pending)"
            )
            for idx, entry in enumerate(entries, start=1)
        ]
        roast = await _last_place_roast(bot, entries)
        await interaction.followup.send("**Leaderboard by Net Profit**\n" + "\n".join(rows) + f"\n\n{roast}")


async def _last_place_roast(bot: DegenBot, entries: list[LeaderboardEntry]) -> str:
    if len(entries) < 2:
        return "Single-player leaderboard energy. Historic levels of bravery."
    return await bot.persona_client.last_place_roast(entries[-1])


def _daily_embed(content: str) -> discord.Embed:
    embed = discord.Embed(
        title="The Degen Bot Daily Drop",
        description=content[:4000],
        color=discord.Color.gold(),
        timestamp=datetime.now(),
    )
    embed.set_footer(text="Fake dollars. Real shame.")
    return embed


def _can_resolve_bets(interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction, "permissions", None)
    return bool(getattr(permissions, "administrator", False))


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    if not settings.discord_token:
        raise SystemExit("DISCORD_TOKEN is required")
    bot = DegenBot(settings)
    asyncio.run(bot.start(settings.discord_token))
