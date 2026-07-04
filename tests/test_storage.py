import pytest

from parlaybot.storage import BetStore


def test_log_bet_and_resolve_win_with_plus_odds(tmp_path):
    store = BetStore(str(tmp_path / "bets.sqlite3"))
    store.initialize()

    bet = store.log_bet(1, "Shane", 50, "Brazil ML", odds=150)
    resolved = store.resolve_bet(bet.id, "win")

    assert resolved.result == "win"
    assert resolved.profit == 75


def test_resolve_loss_and_push_profit(tmp_path):
    store = BetStore(str(tmp_path / "bets.sqlite3"))
    store.initialize()

    loss = store.resolve_bet(store.log_bet(1, "Shane", 50, "Brazil ML").id, "loss")
    push = store.resolve_bet(store.log_bet(1, "Shane", 30, "USA draw").id, "push")

    assert loss.profit == -50
    assert push.profit == 0


def test_resolve_rejects_double_grade(tmp_path):
    store = BetStore(str(tmp_path / "bets.sqlite3"))
    store.initialize()

    bet = store.log_bet(1, "Shane", 50, "Brazil ML")
    store.resolve_bet(bet.id, "loss")

    with pytest.raises(ValueError):
        store.resolve_bet(bet.id, "win")


def test_leaderboard_sorts_by_net_profit(tmp_path):
    store = BetStore(str(tmp_path / "bets.sqlite3"))
    store.initialize()

    store.resolve_bet(store.log_bet(1, "Winner", 100, "A", odds=200).id, "win")
    store.resolve_bet(store.log_bet(2, "Loser", 100, "B").id, "loss")
    store.log_bet(2, "Loser", 25, "C")

    entries = store.leaderboard()

    assert [entry.username for entry in entries] == ["Winner", "Loser"]
    assert entries[0].net_profit == 200
    assert entries[1].pending == 1


def test_log_bet_validates_amount_and_pick(tmp_path):
    store = BetStore(str(tmp_path / "bets.sqlite3"))
    store.initialize()

    with pytest.raises(ValueError):
        store.log_bet(1, "Shane", 0, "Brazil ML")
    with pytest.raises(ValueError):
        store.log_bet(1, "Shane", 1, " ")

