from parlaybot.odds import EventOdds, OutcomeOdds
from parlaybot.picks import choose_daily_picks


def test_choose_daily_picks_selects_plus_money_straight_and_multi_leg_parlay():
    events = [
        EventOdds("1", "soccer", None, "USA", "Brazil", (OutcomeOdds("Brazil", {"fanduel": 140}),)),
        EventOdds("2", "soccer", None, "France", "Japan", (OutcomeOdds("France", {"fanduel": -120}),)),
        EventOdds("3", "soccer", None, "Spain", "Canada", (OutcomeOdds("Canada", {"fanduel": 180}),)),
    ]

    picks = choose_daily_picks(events)

    assert picks.straight is not None
    assert picks.straight.selection == "Canada"
    assert len(picks.parlay) >= 2
    assert picks.parlay_odds is not None


def test_choose_daily_picks_handles_empty_board():
    picks = choose_daily_picks([])

    assert picks.straight is None
    assert picks.parlay == ()
    assert picks.parlay_odds is None

