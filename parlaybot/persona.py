from __future__ import annotations

import aiohttp

from .odds import EventOdds, format_american
from .picks import DailyPicks
from .storage import LeaderboardEntry


SAFE_SYSTEM_PROMPT = (
    "You are The Degen Bot for a private friend-group Discord. "
    "Write funny, aggressive sports betting trash talk. Avoid slurs, protected-class insults, "
    "real threats, doxxing, or harassment that would break Discord rules. "
    "Do not claim a bet is guaranteed. Keep it under 120 words."
)


class PersonaClient:
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def daily_drop_copy(self, events: list[EventOdds], picks: DailyPicks) -> str:
        fallback = fallback_daily_copy(picks)
        prompt = _daily_prompt(events, picks)
        return await self._generate(prompt, fallback=fallback)

    async def last_place_roast(self, entry: LeaderboardEntry) -> str:
        fallback = f"{entry.username} is holding up the leaderboard like it owes him rent."
        prompt = (
            f"Roast the last-place bettor in one sentence. Name: {entry.username}. "
            f"Net profit: ${entry.net_profit:.2f}. Keep it safe and not hateful."
        )
        return await self._generate(prompt, fallback=fallback)

    async def _generate(self, prompt: str, fallback: str) -> str:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": f"{SAFE_SYSTEM_PROMPT}\n\n{prompt}",
            "stream": False,
            "options": {"temperature": 0.8, "num_predict": 180},
        }
        timeout = aiohttp.ClientTimeout(total=20)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as response:
                    if response.status >= 400:
                        return fallback
                    data = await response.json()
        except (aiohttp.ClientError, TimeoutError):
            return fallback

        text = str(data.get("response", "")).strip()
        return text or fallback


def fallback_daily_copy(picks: DailyPicks) -> str:
    if picks.straight is None:
        return "Board is dryer than your bankroll after a Sunday night chase. No official nuke today."
    return (
        f"The card has spoken: {picks.straight.selection} "
        f"({format_american(picks.straight.odds)}) is the move. "
        "Bet imaginary money responsibly, which means at least pretend you thought about it."
    )


def _daily_prompt(events: list[EventOdds], picks: DailyPicks) -> str:
    slate = "; ".join(event.matchup for event in events[:8]) or "No listed games"
    straight = (
        f"{picks.straight.selection} {format_american(picks.straight.odds)} in {picks.straight.matchup}"
        if picks.straight
        else "No straight pick"
    )
    parlay = ", ".join(
        f"{pick.selection} {format_american(pick.odds)}" for pick in picks.parlay
    ) or "No parlay"
    return (
        f"Today's slate: {slate}\n"
        f"Straight pick: {straight}\n"
        f"Parlay: {parlay} at {format_american(picks.parlay_odds)}\n"
        "Write Discord embed intro copy in the bot persona."
    )

