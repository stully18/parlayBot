from __future__ import annotations

from dataclasses import dataclass

from .odds import EventOdds, OutcomeOdds, PropOdds, american_to_decimal, find_event, parlay_american_odds


@dataclass(frozen=True)
class Pick:
    matchup: str
    selection: str
    odds: int
    market: str = "Moneyline"
    conflict_key: str | None = None


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
    prop_odds: list[PropOdds] | None = None,
    min_odds: int = 101,
    max_odds: int = 999,
) -> BuiltParlay | None:
    if leg_count < 2 or leg_count > 6:
        raise ValueError("Parlay legs must be between 2 and 6")

    anchor = find_event(events, query)
    if anchor is None:
        return None

    prop_picks = [_pick_from_prop(prop) for prop in prop_odds or [] if prop.consensus is not None]
    anchor_candidates = list(prop_picks)
    anchor_moneyline = _best_pick_for_event(anchor)
    if anchor_moneyline is not None:
        anchor_candidates.append(anchor_moneyline)

    other_moneylines = [
        pick
        for event in events
        if event.matchup != anchor.matchup
        for pick in [_best_pick_for_event(event)]
        if pick is not None
    ]
    pool = [*anchor_candidates, *other_moneylines]
    pool.sort(key=_parlay_leg_probability, reverse=True)
    pool = pool[:32]
    if len(pool) < leg_count or not anchor_candidates:
        return None

    best: tuple[Pick, ...] | None = None
    best_odds: int | None = None
    best_probability = -1.0

    for legs in _combinations(pool, leg_count):
        if not any(pick in anchor_candidates for pick in legs):
            continue
        if prop_picks and not any(pick in prop_picks for pick in legs):
            continue
        if _has_conflicting_legs(legs):
            continue
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
    return Pick(
        matchup=event.matchup,
        selection=f"{outcome.name} ML",
        odds=outcome.consensus,
        market="Moneyline",
        conflict_key=f"{event.matchup}:moneyline",
    )


def _pick_from_prop(prop: PropOdds) -> Pick:
    return Pick(
        matchup=prop.matchup,
        selection=prop.selection,
        odds=prop.consensus,
        market=prop.market_name,
        conflict_key=prop.conflict_key,
    )


def _parlay_leg_probability(pick: Pick) -> float:
    return _implied_probability(pick.odds)


def _combined_implied_probability(legs: tuple[Pick, ...]) -> float:
    probability = 1.0
    for leg in legs:
        probability *= _parlay_leg_probability(leg)
    return probability


def _has_conflicting_legs(legs: tuple[Pick, ...]) -> bool:
    seen: set[str] = set()
    for leg in legs:
        if not leg.conflict_key:
            continue
        if leg.conflict_key in seen:
            return True
        seen.add(leg.conflict_key)
    return False


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
