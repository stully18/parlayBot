from types import SimpleNamespace
from zoneinfo import ZoneInfo

from parlaybot.bot import _can_resolve_bets, _send_daily_drop
from parlaybot.config import Settings, check_settings
from parlaybot.daily import DailyDrop
from parlaybot.picks import DailyPicks


def test_can_resolve_bets_requires_admin_permission():
    denied = SimpleNamespace(permissions=SimpleNamespace(administrator=False))
    allowed = SimpleNamespace(permissions=SimpleNamespace(administrator=True))

    assert _can_resolve_bets(denied) is False
    assert _can_resolve_bets(allowed) is True


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
