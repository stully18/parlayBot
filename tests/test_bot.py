from types import SimpleNamespace
from zoneinfo import ZoneInfo

from parlaybot.bot import _can_resolve_bets, _discord_invite_url, _parlay_embed, _send_daily_drop
from parlaybot.config import Settings, check_settings
from parlaybot.daily import DailyDrop
from parlaybot.odds import EventOdds, OutcomeOdds
from parlaybot.picks import BuiltParlay, DailyPicks, Pick


def test_can_resolve_bets_requires_admin_permission():
    denied = SimpleNamespace(permissions=SimpleNamespace(administrator=False))
    allowed = SimpleNamespace(permissions=SimpleNamespace(administrator=True))

    assert _can_resolve_bets(denied) is False
    assert _can_resolve_bets(allowed) is True


def test_discord_invite_url_includes_command_scope():
    url = _discord_invite_url(123)

    assert "client_id=123" in url
    assert "scope=bot+applications.commands" in url


def test_parlay_embed_includes_bookmaker_links_for_each_leg():
    anchor = EventOdds(
        event_id="game-1",
        sport_key="soccer_fifa_world_cup",
        commence_time=None,
        home_team="France",
        away_team="Paraguay",
        outcomes=(OutcomeOdds(name="France", prices={"draftkings": -300}),),
    )
    built = BuiltParlay(
        anchor=anchor,
        legs=(
            Pick(
                matchup="Paraguay at France",
                selection="France ML",
                odds=-300,
                bookmaker_keys=("bet365", "draftkings", "fanduel"),
            ),
        ),
        odds=133,
    )

    embed = _parlay_embed(built)

    field_value = embed.fields[0].value
    assert "[Bet365](https://www.bet365.com/)" in field_value
    assert "[DraftKings](https://sportsbook.draftkings.com/)" in field_value
    assert "[FanDuel](https://sportsbook.fanduel.com/)" in field_value


def test_parlay_embed_includes_shared_bookmaker_link_at_bottom():
    anchor = EventOdds(
        event_id="game-1",
        sport_key="soccer_fifa_world_cup",
        commence_time=None,
        home_team="France",
        away_team="Paraguay",
        outcomes=(OutcomeOdds(name="France", prices={"fanduel": -300}),),
    )
    built = BuiltParlay(
        anchor=anchor,
        legs=(
            Pick(
                matchup="Paraguay at France",
                selection="Over 11.5 Total Corners",
                odds=-310,
                bookmaker_keys=("fanduel",),
            ),
            Pick(
                matchup="Paraguay at France",
                selection="Ousmane Dembele Over 0.5 Shots on Target",
                odds=-125,
                bookmaker_keys=("fanduel",),
            ),
        ),
        odds=141,
    )

    embed = _parlay_embed(built)

    build_field = embed.fields[-1]
    assert build_field.name == "Build Parlay"
    assert "[FanDuel](https://sportsbook.fanduel.com/)" in build_field.value


def test_parlay_embed_skips_bottom_link_without_shared_bookmaker():
    anchor = EventOdds(
        event_id="game-1",
        sport_key="soccer_fifa_world_cup",
        commence_time=None,
        home_team="France",
        away_team="Paraguay",
        outcomes=(OutcomeOdds(name="France", prices={"fanduel": -300}),),
    )
    built = BuiltParlay(
        anchor=anchor,
        legs=(
            Pick(matchup="Paraguay at France", selection="France ML", odds=-300, bookmaker_keys=("fanduel",)),
            Pick(matchup="Paraguay at France", selection="Over 2.5 Shots", odds=-125, bookmaker_keys=("bet365",)),
        ),
        odds=141,
    )

    embed = _parlay_embed(built)

    assert all(field.name != "Build Parlay" for field in embed.fields)


def test_check_settings_reports_missing_token_as_error():
    settings = Settings(
        discord_token="",
        discord_guild_id=None,
        discord_channel_id=None,
        odds_api_key=None,
        odds_provider="the_odds_api",
        sport_key="soccer_fifa_world_cup",
        bookmakers=("draftkings", "fanduel"),
        ollama_base_url="http://localhost:11434",
        ollama_model="llama3",
        database_path="./data/test.sqlite3",
        timezone=ZoneInfo("America/New_York"),
    )

    check = check_settings(settings)

    assert check.ok is False
    assert any("DISCORD_TOKEN" in error for error in check.errors)
    assert any("ODDS_API_KEY" in warning for warning in check.warnings)


async def test_send_daily_drop_posts_and_records():
    drop = DailyDrop(events=[], picks=DailyPicks(straight=None, parlay=(), parlay_odds=None), copy="copy")
    service = SimpleNamespace(build_drop=_async_return(drop), record_drop=lambda built, channel_id: None)
    bot = SimpleNamespace(daily_service=service)
    channel = FakeChannel()

    await _send_daily_drop(bot, channel, 123)

    assert len(channel.embeds) == 1
    assert channel.embeds[0].title == "The Degen Bot Daily Drop"


class FakeChannel:
    def __init__(self):
        self.embeds = []

    async def send(self, *, embed):
        self.embeds.append(embed)


def _async_return(value):
    async def inner():
        return value

    return inner
