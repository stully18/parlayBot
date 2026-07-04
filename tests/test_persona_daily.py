from parlaybot.daily import DailyDropService
from parlaybot.odds import EventOdds, OddsError, OutcomeOdds
from parlaybot.persona import fallback_daily_copy
from parlaybot.picks import DailyPicks, Pick


def test_fallback_daily_copy_with_no_picks():
    text = fallback_daily_copy(DailyPicks(straight=None, parlay=(), parlay_odds=None))

    assert "No official" in text


class FailingOddsClient:
    async def fetch_odds(self, sport_key):
        raise OddsError("nope")


class StaticPersonaClient:
    async def daily_drop_copy(self, events, picks):
        return "LLM copy"


class NullStore:
    def record_daily_drop(self, drop_date, sport_key, channel_id, content):
        self.recorded = (drop_date, sport_key, channel_id, content)


def test_daily_drop_falls_back_when_odds_fail():
    service = DailyDropService(FailingOddsClient(), StaticPersonaClient(), NullStore(), "soccer")

    import asyncio

    drop = asyncio.run(service.build_drop())

    assert drop.events == []
    assert "No official" in drop.copy


class StaticOddsClient:
    async def fetch_odds(self, sport_key):
        return [
            EventOdds("1", sport_key, None, "USA", "Brazil", (OutcomeOdds("Brazil", {"fanduel": 150}),)),
            EventOdds("2", sport_key, None, "France", "Japan", (OutcomeOdds("France", {"fanduel": -110}),)),
        ]


def test_daily_drop_uses_persona_when_odds_exist():
    service = DailyDropService(StaticOddsClient(), StaticPersonaClient(), NullStore(), "soccer")

    import asyncio

    drop = asyncio.run(service.build_drop())

    assert drop.copy == "LLM copy"
    assert "Pick of the Day" in drop.content

