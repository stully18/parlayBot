from __future__ import annotations

from dataclasses import dataclass

from .odds import EventOdds, OutcomeOdds, parlay_american_odds


@dataclass(frozen=True)
class Pick:
    matchup: str
    selection: str
    odds: int


@dataclass(frozen=True)
class DailyPicks:
    straight: Pick | None
    parlay: tuple[Pick, ...]
    parlay_odds: int | None


def choose_daily_picks(events: list[EventOdds]) -> DailyPicks:
    candidates = [
        Pick(matchup=event.matchup, selection=outcome.name, odds=outcome.consensus)
        for event in events
        for outcome in event.outcomes
        if outcome.consensus is not None
    ]
    if not candidates:
        return DailyPicks(straight=None, parlay=(), parlay_odds=None)

    straight = max(candidates, key=_straight_score)

    parlay: list[Pick] = []
    used_matchups: set[str] = set()
    for pick in sorted(candidates, key=_parlay_score, reverse=True):
        if pick.matchup in used_matchups:
            continue
        if not -250 <= pick.odds <= 250:
            continue
        parlay.append(pick)
        used_matchups.add(pick.matchup)
        if len(parlay) == 3:
            break

    if len(parlay) < 2:
        parlay = [straight]

    combined = parlay_american_odds([pick.odds for pick in parlay]) if len(parlay) >= 2 else None
    return DailyPicks(straight=straight, parlay=tuple(parlay), parlay_odds=combined)


def outcome_source_label(outcome: OutcomeOdds) -> str:
    books = ", ".join(sorted(outcome.prices))
    return books or "no books"


def _straight_score(pick: Pick) -> tuple[int, int]:
    # Favor plus-money without drifting into pure lottery-ticket territory.
    if 100 <= pick.odds <= 220:
        bucket = 3
    elif -130 <= pick.odds < 100:
        bucket = 2
    elif 220 < pick.odds <= 350:
        bucket = 1
    else:
        bucket = 0
    return (bucket, pick.odds)


def _parlay_score(pick: Pick) -> int:
    return -abs(pick.odds - 110)

