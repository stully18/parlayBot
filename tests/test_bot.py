from types import SimpleNamespace

from parlaybot.bot import _can_resolve_bets


def test_can_resolve_bets_requires_admin_permission():
    denied = SimpleNamespace(permissions=SimpleNamespace(administrator=False))
    allowed = SimpleNamespace(permissions=SimpleNamespace(administrator=True))

    assert _can_resolve_bets(denied) is False
    assert _can_resolve_bets(allowed) is True
