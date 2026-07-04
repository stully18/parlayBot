from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

import aiohttp


SUPPORTED_MARKETS = ("h2h",)
BOOKMAKER_TITLES = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
}


@dataclass(frozen=True)
class OutcomeOdds:
    name: str
    prices: dict[str, int]

    @property
    def consensus(self) -> int | None:
        if not self.prices:
            return None
        return round(sum(self.prices.values()) / len(self.prices))


@dataclass(frozen=True)
class EventOdds:
    event_id: str
    sport_key: str
    commence_time: datetime | None
    home_team: str
    away_team: str
    outcomes: tuple[OutcomeOdds, ...]

    @property
    def matchup(self) -> str:
        return f"{self.away_team} at {self.home_team}"


class OddsError(RuntimeError):
    pass


def american_to_decimal(american: int) -> float:
    if american > 0:
        return 1 + american / 100
    if american < 0:
        return 1 + 100 / abs(american)
    raise ValueError("American odds cannot be 0")


def decimal_to_american(decimal_odds: float) -> int:
    if decimal_odds <= 1:
        raise ValueError("Decimal odds must be greater than 1")
    if decimal_odds >= 2:
        return round((decimal_odds - 1) * 100)
    return round(-100 / (decimal_odds - 1))


def parlay_american_odds(legs: list[int] | tuple[int, ...]) -> int:
    if not legs:
        raise ValueError("At least one parlay leg is required")
    combined = 1.0
    for leg in legs:
        combined *= american_to_decimal(leg)
    return decimal_to_american(combined)


def normalize_events(
    payload: list[dict[str, Any]],
    sport_key: str,
    bookmakers: tuple[str, ...] = ("draftkings", "fanduel"),
) -> list[EventOdds]:
    bookmaker_set = {book.lower() for book in bookmakers}
    events: list[EventOdds] = []

    for raw_event in payload:
        outcomes_by_name: dict[str, dict[str, int]] = {}
        for bookmaker in raw_event.get("bookmakers", []):
            key = str(bookmaker.get("key", "")).lower()
            if key not in bookmaker_set:
                continue

            for market in bookmaker.get("markets", []):
                if market.get("key") not in SUPPORTED_MARKETS:
                    continue
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name")
                    price = outcome.get("price")
                    if not name or not isinstance(price, int):
                        continue
                    outcomes_by_name.setdefault(name, {})[key] = price

        outcomes = tuple(
            OutcomeOdds(name=name, prices=dict(sorted(prices.items())))
            for name, prices in sorted(outcomes_by_name.items())
        )
        if not outcomes:
            continue

        events.append(
            EventOdds(
                event_id=str(raw_event.get("id", "")),
                sport_key=sport_key,
                commence_time=_parse_datetime(raw_event.get("commence_time")),
                home_team=str(raw_event.get("home_team", "")),
                away_team=str(raw_event.get("away_team", "")),
                outcomes=outcomes,
            )
        )

    return events


def find_event(events: list[EventOdds], query: str) -> EventOdds | None:
    needle = query.strip().lower()
    if not needle:
        return None

    best_score = 0.0
    best_event: EventOdds | None = None
    for event in events:
        haystacks = (
            event.matchup.lower(),
            event.home_team.lower(),
            event.away_team.lower(),
            f"{event.home_team} {event.away_team}".lower(),
        )
        score = max(_match_score(needle, haystack) for haystack in haystacks)
        if score > best_score:
            best_score = score
            best_event = event

    return best_event if best_score >= 0.45 else None


class OddsClient:
    def __init__(self, api_key: str | None, bookmakers: tuple[str, ...]) -> None:
        self.api_key = api_key
        self.bookmakers = bookmakers

    async def fetch_odds(self, sport_key: str) -> list[EventOdds]:
        if not self.api_key:
            raise OddsError("ODDS_API_KEY is not configured")

        params = {
            "apiKey": self.api_key,
            "regions": "us",
            "markets": ",".join(SUPPORTED_MARKETS),
            "oddsFormat": "american",
            "bookmakers": ",".join(self.bookmakers),
        }
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise OddsError(f"Odds API returned {response.status}: {text[:200]}")
                payload = await response.json()

        if not isinstance(payload, list):
            raise OddsError("Odds API returned an unexpected payload")
        return normalize_events(payload, sport_key=sport_key, bookmakers=self.bookmakers)


def format_american(odds: int | None) -> str:
    if odds is None:
        return "n/a"
    return f"+{odds}" if odds > 0 else str(odds)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _match_score(needle: str, haystack: str) -> float:
    if needle in haystack:
        return 1.0
    return SequenceMatcher(None, needle, haystack).ratio()

