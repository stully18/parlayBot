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
    target_odds: int | None = None


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
    anchor_events: list[EventOdds] | None = None,
    target_odds: int | None = None,
    include_unrequested_games: bool = True,
    min_odds: int = 101,
    max_odds: int = 999,
) -> BuiltParlay | None:
    if leg_count < 2 or leg_count > 6:
        raise ValueError("Parlay legs must be between 2 and 6")
    if target_odds is not None and not 100 <= target_odds <= 1000:
        raise ValueError("Target odds must be between +100 and +1000")

    if target_odds is not None:
        min_odds = max(101, target_odds - 50)
        max_odds = min(999, target_odds + 50)

    anchors = anchor_events or _find_requested_events(events, query)
    if not anchors:
        return None
    anchor_matchups = {event.matchup for event in anchors}
    anchor = anchors[0]

    prop_picks = [
        _pick_from_prop(prop)
        for prop in prop_odds or []
        if prop.consensus is not None and _valid_american_odds(prop.consensus)
    ]
    prop_picks = [pick for pick in prop_picks if pick.matchup in anchor_matchups]
    anchor_candidates = list(prop_picks)
    anchor_moneylines = [
        pick
        for event in anchors
        for pick in [_best_pick_for_event(event)]
        if pick is not None
    ]
    anchor_candidates.extend(anchor_moneylines)

    other_moneylines = []
    if include_unrequested_games:
        other_moneylines = [
            pick
            for event in events
            if event.matchup not in anchor_matchups
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
        if _anchor_leg_count(legs, anchor_matchups) < min(len(anchor_matchups), leg_count):
            continue
        combined_odds = parlay_american_odds([pick.odds for pick in legs])
        if not min_odds <= combined_odds <= max_odds:
            continue

        probability = _combined_implied_probability(legs)
        if _is_better_parlay(
            current_odds=combined_odds,
            current_probability=probability,
            best_odds=best_odds,
            best_probability=best_probability,
            target_odds=target_odds,
        ):
            best = legs
            best_odds = combined_odds
            best_probability = probability

    if best is None or best_odds is None:
        return None
    return BuiltParlay(anchor=anchor, legs=best, odds=best_odds, target_odds=target_odds)


def find_requested_events(events: list[EventOdds], query: str) -> list[EventOdds]:
    return _find_requested_events(events, query)


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
    priced = [
        outcome
        for outcome in event.outcomes
        if outcome.consensus is not None and _valid_american_odds(outcome.consensus)
    ]
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


def _anchor_leg_count(legs: tuple[Pick, ...], anchor_matchups: set[str]) -> int:
    return len({leg.matchup for leg in legs if leg.matchup in anchor_matchups})


def _is_better_parlay(
    current_odds: int,
    current_probability: float,
    best_odds: int | None,
    best_probability: float,
    target_odds: int | None,
) -> bool:
    if best_odds is None:
        return True
    if target_odds is not None:
        current_distance = abs(current_odds - target_odds)
        best_distance = abs(best_odds - target_odds)
        return current_distance < best_distance or (
            current_distance == best_distance and current_probability > best_probability
        )
    return current_odds < best_odds or (current_odds == best_odds and current_probability > best_probability)


def _implied_probability(odds: int | None) -> float:
    if odds is None or not _valid_american_odds(odds):
        return 0.0
    return 1 / american_to_decimal(odds)


def _valid_american_odds(odds: int) -> bool:
    return odds != 0


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


def _find_requested_events(events: list[EventOdds], query: str) -> list[EventOdds]:
    parts = [part.strip() for part in query.split(",") if part.strip()]
    if not parts:
        parts = [query]

    requested: list[EventOdds] = []
    seen: set[str] = set()
    for part in parts:
        event = find_event(events, part)
        if event is None or event.event_id in seen:
            continue
        requested.append(event)
        seen.add(event.event_id)
    return requested
