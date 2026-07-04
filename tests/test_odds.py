from parlaybot.odds import (
    decimal_to_american,
    find_event,
    format_american,
    normalize_events,
    parlay_american_odds,
)


def test_normalize_events_filters_books_and_computes_consensus():
    payload = [
        {
            "id": "game-1",
            "commence_time": "2026-06-11T19:00:00Z",
            "home_team": "USA",
            "away_team": "Brazil",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "markets": [{"key": "h2h", "outcomes": [{"name": "USA", "price": 150}]}],
                },
                {
                    "key": "fanduel",
                    "markets": [{"key": "h2h", "outcomes": [{"name": "USA", "price": 130}]}],
                },
                {
                    "key": "betmgm",
                    "markets": [{"key": "h2h", "outcomes": [{"name": "USA", "price": -999}]}],
                },
            ],
        }
    ]

    events = normalize_events(payload, "soccer_fifa_world_cup")

    assert len(events) == 1
    assert events[0].matchup == "Brazil at USA"
    assert events[0].outcomes[0].prices == {"draftkings": 150, "fanduel": 130}
    assert events[0].outcomes[0].consensus == 140


def test_normalize_events_allows_one_available_target_book():
    payload = [
        {
            "id": "game-1",
            "home_team": "France",
            "away_team": "Germany",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "markets": [{"key": "h2h", "outcomes": [{"name": "France", "price": -120}]}],
                }
            ],
        }
    ]

    events = normalize_events(payload, "soccer_fifa_world_cup")

    assert events[0].outcomes[0].consensus == -120


def test_find_event_matches_partial_team_name():
    events = normalize_events(
        [
            {
                "id": "game-1",
                "home_team": "Argentina",
                "away_team": "Japan",
                "bookmakers": [
                    {
                        "key": "fanduel",
                        "markets": [{"key": "h2h", "outcomes": [{"name": "Argentina", "price": -150}]}],
                    }
                ],
            }
        ],
        "soccer_fifa_world_cup",
    )

    assert find_event(events, "arg") is events[0]


def test_parlay_american_odds():
    assert parlay_american_odds([100, 100]) == 300
    assert parlay_american_odds([-110, -110]) == 264


def test_decimal_to_american_and_format():
    assert decimal_to_american(2.5) == 150
    assert decimal_to_american(1.5) == -200
    assert format_american(150) == "+150"
    assert format_american(-120) == "-120"
    assert format_american(None) == "n/a"

