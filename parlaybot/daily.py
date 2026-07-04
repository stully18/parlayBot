from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .odds import EventOdds, OddsClient, OddsError, format_american
from .persona import PersonaClient, fallback_daily_copy
from .picks import DailyPicks, Pick, choose_daily_picks
from .storage import BetStore


@dataclass(frozen=True)
class DailyDrop:
    events: list[EventOdds]
    picks: DailyPicks
    copy: str

    @property
    def content(self) -> str:
        slate = "\n".join(f"- {event.matchup}" for event in self.events[:10]) or "- No games found"
        straight = _format_pick(self.picks.straight) if self.picks.straight else "No straight pick available"
        parlay_legs = "\n".join(f"- {_format_pick(pick)}" for pick in self.picks.parlay) or "- No parlay available"
        parlay_odds = format_american(self.picks.parlay_odds)
        return (
            f"{self.copy}\n\n"
            f"**Today's Slate**\n{slate}\n\n"
            f"**Pick of the Day**\n{straight}\n\n"
            f"**Parlay of the Day ({parlay_odds})**\n{parlay_legs}"
        )


class DailyDropService:
    def __init__(
        self,
        odds_client: OddsClient,
        persona_client: PersonaClient,
        store: BetStore,
        sport_key: str,
    ) -> None:
        self.odds_client = odds_client
        self.persona_client = persona_client
        self.store = store
        self.sport_key = sport_key

    async def build_drop(self) -> DailyDrop:
        try:
            events = await self.odds_client.fetch_odds(self.sport_key)
        except OddsError:
            events = []

        picks = choose_daily_picks(events)
        if events:
            copy = await self.persona_client.daily_drop_copy(events, picks)
        else:
            copy = fallback_daily_copy(picks)
        return DailyDrop(events=events, picks=picks, copy=copy)

    def record_drop(self, drop: DailyDrop, channel_id: int | None) -> None:
        self.store.record_daily_drop(
            drop_date=date.today().isoformat(),
            sport_key=self.sport_key,
            channel_id=channel_id,
            content=drop.content,
        )


def _format_pick(pick: Pick) -> str:
    return f"{pick.selection} ({format_american(pick.odds)}) - {pick.matchup}"

