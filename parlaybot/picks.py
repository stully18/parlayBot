from __future__ import annotations

from dataclasses import dataclass

from .odds import EventOdds, OutcomeOdds, american_to_decimal, find_event, parlay_american_odds


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


@dataclass(frozen=True)
class BuiltParlay:
    anchor: EventOdds
    legs: tuple[Pick, ...]
    odds: int


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


def build_best_parlay(
    events: list[EventOdds],
    query: str,
    leg_count: int,
    min_odds: int = 101,
    max_odds: int = 999,
) -> BuiltParlay | None:
    if leg_count < 2 or leg_count > 6:
        raise ValueError("Parlay legs must be between 2 and 6")

    anchor = find_event(events, query)
    if anchor is None:
        return None

    best_by_event = [_best_pick_for_event(event) for event in events]
    candidates = [pick for pick in best_by_event if pick is not None]
    if len(candidates) < leg_count:
        return None

    anchor_pick = _best_pick_for_event(anchor)
    if anchor_pick is None:
        return None

    pool = [pick for pick in candidates if pick.matchup != anchor.matchup]
    pool.sort(key=_parlay_leg_probability, reverse=True)
    pool = pool[:24]

    best: tuple[Pick, ...] | None = None
    best_odds: int | None = None
    best_probability = -1.0

    for combo in _combinations(pool, leg_count - 1):
        legs = (anchor_pick, *combo)
        combined_odds = parlay_american_odds([pick.odds for pick in legs])
        if not min_odds <= combined_odds <= max_odds:
            continue

        probability = _combined_implied_probability(legs)
        if best is None or combined_odds < best_odds or (
            combined_odds == best_odds and probability > best_probability
        ):
            best = legs
            best_odds = combined_odds
            best_probability = probability

    if best is None or best_odds is None:
        return None
    return BuiltParlay(anchor=anchor, legs=best, odds=best_odds)


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


def _best_pick_for_event(event: EventOdds) -> Pick | None:
    priced = [outcome for outcome in event.outcomes if outcome.consensus is not None]
    if not priced:
        return None
    outcome = max(priced, key=lambda candidate: _implied_probability(candidate.consensus))
    return Pick(matchup=event.matchup, selection=outcome.name, odds=outcome.consensus)


def _parlay_leg_probability(pick: Pick) -> float:
    return _implied_probability(pick.odds)


def _combined_implied_probability(legs: tuple[Pick, ...]) -> float:
    probability = 1.0
    for leg in legs:
        probability *= _parlay_leg_probability(leg)
    return probability


def _implied_probability(odds: int | None) -> float:
    if odds is None:
        return 0.0
    return 1 / american_to_decimal(odds)


def _combinations(pool: list[Pick], size: int) -> list[tuple[Pick, ...]]:
    if size == 0:
        return [()]
    if size > len(pool):
        return []

    combos: list[tuple[Pick, ...]] = []

    def walk(start: int, current: list[Pick]) -> None:
        if len(current) == size:
            combos.append(tuple(current))
            return
        remaining_slots = size - len(current)
        for index in range(start, len(pool) - remaining_slots + 1):
            current.append(pool[index])
            walk(index + 1, current)
            current.pop()

    walk(0, [])
    return combos
