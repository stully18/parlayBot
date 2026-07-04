from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from time import monotonic
from typing import Any

import aiohttp


SUPPORTED_MARKETS = ("h2h",)
SOCCER_PROP_MARKETS = (
    "player_goal_scorer_anytime",
    "player_first_goal_scorer",
    "player_last_goal_scorer",
    "player_to_receive_card",
    "player_to_receive_red_card",
    "player_shots_on_target",
    "player_shots",
    "player_assists",
)
SOCCER_GAME_MARKETS = (
    "btts",
    "alternate_totals_corners",
    "alternate_totals_cards",
    "double_chance",
)
PROP_MARKET_NAMES = {
    "player_goal_scorer_anytime": "Anytime Goal Scorer",
    "player_first_goal_scorer": "First Goal Scorer",
    "player_last_goal_scorer": "Last Goal Scorer",
    "player_to_receive_card": "Card",
    "player_to_receive_red_card": "Red Card",
    "player_shots_on_target": "Shots on Target",
    "player_shots": "Shots",
    "player_assists": "Assists",
    "btts": "Both Teams to Score",
    "alternate_totals_corners": "Total Corners",
    "alternate_totals_cards": "Total Cards",
    "double_chance": "Double Chance",
}
BOOKMAKER_TITLES = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
}
BOOKMAKER_LINKS = {
    "draftkings": "https://sportsbook.draftkings.com/",
    "fanduel": "https://sportsbook.fanduel.com/",
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


@dataclass(frozen=True)
class PropOdds:
    matchup: str
    market_key: str
    market_name: str
    selection: str
    prices: dict[str, int]
    conflict_key: str

    @property
    def consensus(self) -> int | None:
        if not self.prices:
            return None
        return round(sum(self.prices.values()) / len(self.prices))


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


def normalize_event_props(
    payload: dict[str, Any],
    bookmakers: tuple[str, ...] = ("draftkings", "fanduel"),
) -> list[PropOdds]:
    bookmaker_set = {book.lower() for book in bookmakers}
    matchup = f"{payload.get('away_team', '')} at {payload.get('home_team', '')}"
    props_by_key: dict[tuple[str, str, str], dict[str, int]] = {}
    labels_by_key: dict[tuple[str, str, str], str] = {}

    for bookmaker in payload.get("bookmakers", []):
        book_key = str(bookmaker.get("key", "")).lower()
        if book_key not in bookmaker_set:
            continue

        for market in bookmaker.get("markets", []):
            market_key = str(market.get("key", ""))
            market_name = PROP_MARKET_NAMES.get(market_key, market_key.replace("_", " ").title())
            for outcome in market.get("outcomes", []):
                price = outcome.get("price")
                if not isinstance(price, int):
                    continue
                name = str(outcome.get("name", "")).strip()
                description = str(outcome.get("description", "")).strip()
                point = outcome.get("point")
                label = _prop_label(market_name, name, description, point)
                if not label:
                    continue

                conflict_key = _prop_conflict_key(market_key, name, description)
                key = (market_key, conflict_key, label)
                props_by_key.setdefault(key, {})[book_key] = price
                labels_by_key[key] = label

    props = [
        PropOdds(
            matchup=matchup,
            market_key=market_key,
            market_name=PROP_MARKET_NAMES.get(market_key, market_key.replace("_", " ").title()),
            selection=labels_by_key[key],
            prices=dict(sorted(prices.items())),
            conflict_key=f"{matchup}:{conflict_key}",
        )
        for key, prices in props_by_key.items()
        for market_key, conflict_key, _label in [key]
    ]
    return sorted(props, key=lambda prop: (prop.market_name, prop.selection))


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
        self.cache_ttl_seconds = 30.0
        self._cache: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def fetch_odds(self, sport_key: str) -> list[EventOdds]:
        if not self.api_key:
            raise OddsError("ODDS_API_KEY is not configured")

        async def load() -> list[EventOdds]:
            params = {
                "apiKey": self.api_key,
                "regions": "us",
                "markets": ",".join(SUPPORTED_MARKETS),
                "oddsFormat": "american",
                "bookmakers": ",".join(self.bookmakers),
            }
            url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
            payload = await self._request_json(url, params=params)

            if not isinstance(payload, list):
                raise OddsError("Odds API returned an unexpected payload")
            return normalize_events(payload, sport_key=sport_key, bookmakers=self.bookmakers)

        return list(await self._cached(f"odds:{sport_key}", load))

    async def fetch_event_markets(self, sport_key: str, event_id: str) -> tuple[str, ...]:
        if not self.api_key:
            raise OddsError("ODDS_API_KEY is not configured")

        async def load() -> tuple[str, ...]:
            params = {
                "apiKey": self.api_key,
                "regions": "us",
                "bookmakers": ",".join(self.bookmakers),
            }
            url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/events/{event_id}/markets"
            payload = await self._request_json(url, params=params)

            if not isinstance(payload, dict):
                raise OddsError("Odds API returned an unexpected event-markets payload")

            markets: set[str] = set()
            for bookmaker in payload.get("bookmakers", []):
                key = str(bookmaker.get("key", "")).lower()
                if key not in set(self.bookmakers):
                    continue
                for market in bookmaker.get("markets", []):
                    market_key = market.get("key")
                    if isinstance(market_key, str):
                        markets.add(market_key)
            return tuple(sorted(markets))

        return await self._cached(f"markets:{sport_key}:{event_id}", load)

    async def fetch_event_props(self, sport_key: str, event: EventOdds) -> list[PropOdds]:
        async def load() -> list[PropOdds]:
            available_markets = await self.fetch_event_markets(sport_key, event.event_id)
            requested_markets = [
                market
                for market in (*SOCCER_PROP_MARKETS, *SOCCER_GAME_MARKETS)
                if market in available_markets
            ]
            if not requested_markets:
                return []

            params = {
                "apiKey": self.api_key,
                "regions": "us",
                "markets": ",".join(requested_markets),
                "oddsFormat": "american",
                "bookmakers": ",".join(self.bookmakers),
            }
            url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/events/{event.event_id}/odds"
            payload = await self._request_json(url, params=params)

            if not isinstance(payload, dict):
                raise OddsError("Odds API returned an unexpected event-odds payload")
            return normalize_event_props(payload, bookmakers=self.bookmakers)

        return list(await self._cached(f"props:{sport_key}:{event.event_id}", load))

    async def _request_json(self, url: str, params: dict[str, str]) -> Any:
        timeout = aiohttp.ClientTimeout(total=12, connect=5, sock_read=8)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as response:
                    if response.status >= 400:
                        text = await response.text()
                        raise OddsError(f"Odds API returned {response.status}: {text[:200]}")
                    return await response.json()
        except TimeoutError as exc:
            raise OddsError("Odds API request timed out; try again in a few seconds") from exc
        except aiohttp.ClientError as exc:
            raise OddsError(f"Odds API network error: {exc}") from exc

    async def _cached(self, key: str, load):
        cached = self._cache.get(key)
        now = monotonic()
        if cached and now - cached[0] < self.cache_ttl_seconds:
            return cached[1]

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._cache.get(key)
            now = monotonic()
            if cached and now - cached[0] < self.cache_ttl_seconds:
                return cached[1]
            value = await load()
            self._cache[key] = (monotonic(), value)
            return value


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


def _prop_label(market_name: str, name: str, description: str, point: Any) -> str:
    point_text = _format_point(point)
    if description and name in {"Over", "Under"} and point_text:
        return f"{description} {name} {point_text} {market_name}"
    if description and name:
        return f"{description} {name} {market_name}"
    if name and point_text:
        return f"{name} {point_text} {market_name}"
    if name:
        return f"{name} {market_name}"
    return description


def _prop_conflict_key(market_key: str, name: str, description: str) -> str:
    subject = description or name
    return f"{market_key}:{subject}".lower()


def _format_point(point: Any) -> str:
    if point is None:
        return ""
    if isinstance(point, int):
        return str(point)
    if isinstance(point, float) and point.is_integer():
        return str(int(point))
    return str(point)
