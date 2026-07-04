from __future__ import annotations

import asyncio
import argparse
import logging
from datetime import datetime, time

import discord
from discord import app_commands
from discord.ext import tasks

from .config import Settings, check_settings, load_settings
from .daily import DailyDropService
from .odds import BOOKMAKER_LINKS, BOOKMAKER_TITLES, OddsClient, OddsError, find_event, format_american
from .persona import PersonaClient
from .picks import BuiltParlay, build_best_parlay, find_requested_events
from .storage import BetStore, LeaderboardEntry


LOGGER = logging.getLogger(__name__)


class DegenBot(discord.Client):
    def __init__(self, settings: Settings, smoke_test: bool = False) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.settings = settings
        self.smoke_test = smoke_test
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
            try:
                await self.tree.sync(guild=guild)
            except discord.Forbidden as exc:
                invite_url = _discord_invite_url(self.application_id)
                raise RuntimeError(
                    "Discord refused guild command sync with 403 Missing Access. "
                    "Confirm the bot is invited to DISCORD_GUILD_ID with the bot and "
                    f"applications.commands scopes. Invite URL: {invite_url}"
                ) from exc
        else:
            await self.tree.sync()
        self.daily_drop_loop.start()

    async def on_ready(self) -> None:
        LOGGER.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "unknown")
        if self.smoke_test:
            LOGGER.info("Smoke test reached Discord ready; shutting down")
            asyncio.create_task(self.close())

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

        await _send_daily_drop(self, channel, self.settings.discord_channel_id)

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

    @bot.tree.command(name="parlay", description="Build the best live parlay for a matchup.")
    @app_commands.describe(
        matchup="Team/matchup to anchor to. Use commas for multiple games.",
        legs="Number of legs to include, from 2 to 6",
        target_odds="Optional target American odds from +100 to +1000",
    )
    async def parlay(interaction: discord.Interaction, matchup: str, legs: int, target_odds: int | None = None) -> None:
        await interaction.response.defer(thinking=True)
        try:
            events = await bot.odds_client.fetch_odds(bot.settings.sport_key)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except OddsError as exc:
            await interaction.followup.send(f"Live odds are unavailable right now: {exc}", ephemeral=True)
            return

        requested_events = find_requested_events(events, matchup)
        if not requested_events:
            await interaction.followup.send(f"Could not find a matchup for `{matchup}`.", ephemeral=True)
            return

        prop_odds = []
        prop_note = ""
        for event in requested_events:
            try:
                prop_odds.extend(await bot.odds_client.fetch_event_props(bot.settings.sport_key, event))
            except OddsError as exc:
                prop_note = f"Some props could not be fetched, so missing props were skipped: {exc}"

        try:
            built = build_best_parlay(
                events,
                matchup,
                legs,
                prop_odds=prop_odds,
                anchor_events=requested_events,
                target_odds=target_odds,
                include_unrequested_games=False,
            )
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        if built is None and prop_odds:
            built = build_best_parlay(
                events,
                matchup,
                legs,
                anchor_events=requested_events,
                target_odds=target_odds,
                include_unrequested_games=False,
            )
            if built is not None:
                prop_note = "Props were open, but no prop combo fit the odds window. Returned moneylines instead."

        odds_window = _target_window_label(target_odds)
        if built is None:
            await interaction.followup.send(
                f"Could not build a {legs}-leg parlay for `{matchup}` {odds_window}."
                f"{f' {prop_note}' if prop_note else ''}",
                ephemeral=True,
            )
            return

        await interaction.followup.send(embed=_parlay_embed(built, props_checked=True, prop_note=prop_note))

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
    @app_commands.choices(
        result=[
            app_commands.Choice(name="win", value="win"),
            app_commands.Choice(name="loss", value="loss"),
            app_commands.Choice(name="push", value="push"),
        ]
    )
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

    @bot.tree.command(name="dropnow", description="Admin: post the daily drop immediately.")
    async def dropnow(interaction: discord.Interaction) -> None:
        if not _can_resolve_bets(interaction):
            await interaction.response.send_message("Admin only. Go win a mod election first.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        if not isinstance(interaction.channel, discord.abc.Messageable):
            await interaction.followup.send("This channel cannot receive the daily drop.", ephemeral=True)
            return
        await _send_daily_drop(bot, interaction.channel, interaction.channel_id)
        await interaction.followup.send("Daily drop posted.")

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


async def _send_daily_drop(bot: DegenBot, channel: discord.abc.Messageable, channel_id: int | None) -> None:
    drop = await bot.daily_service.build_drop()
    await channel.send(embed=_daily_embed(drop.content))
    bot.daily_service.record_drop(drop, channel_id)


def _daily_embed(content: str) -> discord.Embed:
    embed = discord.Embed(
        title="The Degen Bot Daily Drop",
        description=content[:4000],
        color=discord.Color.gold(),
        timestamp=datetime.now(),
    )
    embed.set_footer(text="Fake dollars. Real shame.")
    return embed


def _parlay_embed(parlay: BuiltParlay, props_checked: bool = False, prop_note: str = "") -> discord.Embed:
    has_prop_leg = any(pick.market != "Moneyline" for pick in parlay.legs)
    target_line = f"\nTarget: {format_american(parlay.target_odds)} +/-50." if parlay.target_odds else ""
    if prop_note:
        prop_status = prop_note
    elif has_prop_leg:
        prop_status = "Props included by default."
    else:
        prop_status = "No props were open for this match."
    embed = discord.Embed(
        title=f"Best Live Parlay {format_american(parlay.odds)}",
        description=(
            f"Anchored to **{parlay.anchor.matchup}**.\n"
            f"Built from live DraftKings/FanDuel consensus odds.{target_line}\n"
            f"{prop_status if props_checked else ''}"
        ),
        color=discord.Color.green(),
        timestamp=datetime.now(),
    )
    for index, pick in enumerate(parlay.legs, start=1):
        book_links = _bookmaker_links(pick.bookmaker_keys)
        value = f"{pick.matchup}\nConsensus {format_american(pick.odds)}"
        if book_links:
            value = f"{value}\nBooks: {book_links}"
        embed.add_field(
            name=f"Leg {index}: {pick.selection}",
            value=value,
            inline=False,
        )
    embed.set_footer(text="Filtered to greater than +100 and less than +1000. Props are tried by default.")
    return embed


def _bookmaker_links(bookmaker_keys: tuple[str, ...]) -> str:
    links = []
    for key in bookmaker_keys:
        url = BOOKMAKER_LINKS.get(key)
        if not url:
            continue
        title = BOOKMAKER_TITLES.get(key, key.title())
        links.append(f"[{title}]({url})")
    return " | ".join(links)


def _target_window_label(target_odds: int | None) -> str:
    if target_odds is None:
        return "between +101 and +999"
    low = max(101, target_odds - 50)
    high = min(999, target_odds + 50)
    return f"between +{low} and +{high}"


def _can_resolve_bets(interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction, "permissions", None)
    return bool(getattr(permissions, "administrator", False))


def _discord_invite_url(application_id: int | None) -> str:
    if application_id is None:
        return "unavailable until Discord login completes"
    permissions = 83968
    return (
        "https://discord.com/oauth2/authorize"
        f"?client_id={application_id}"
        f"&permissions={permissions}"
        "&integration_type=0"
        "&scope=bot+applications.commands"
    )


async def _run_bot(bot: DegenBot, token: str, timeout_seconds: float | None = None) -> None:
    try:
        if timeout_seconds is None:
            await bot.start(token)
        else:
            await asyncio.wait_for(bot.start(token), timeout=timeout_seconds)
    except TimeoutError as exc:
        raise RuntimeError(f"Discord startup smoke test did not become ready within {timeout_seconds:g} seconds") from exc
    finally:
        if not bot.is_closed():
            await bot.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run The Degen Bot.")
    parser.add_argument("--check-config", action="store_true", help="Validate local configuration and exit.")
    parser.add_argument("--init-db", action="store_true", help="Initialize the SQLite database and exit.")
    parser.add_argument("--smoke-test", action="store_true", help="Connect to Discord, sync commands, then exit.")
    parser.add_argument("--smoke-timeout", type=float, default=60.0, help="Seconds to wait for --smoke-test readiness.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    settings = load_settings()

    if args.init_db:
        BetStore(settings.database_path).initialize()
        print(f"Initialized database at {settings.database_path}")
        return

    check = check_settings(settings)
    if args.check_config:
        for warning in check.warnings:
            print(f"WARNING: {warning}")
        for error in check.errors:
            print(f"ERROR: {error}")
        if check.ok:
            print("Config is sufficient to start the bot.")
        raise SystemExit(0 if check.ok else 1)

    if not check.ok:
        raise SystemExit("\n".join(check.errors))

    bot = DegenBot(settings, smoke_test=args.smoke_test)
    try:
        timeout_seconds = args.smoke_timeout if args.smoke_test else None
        asyncio.run(_run_bot(bot, settings.discord_token, timeout_seconds=timeout_seconds))
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
