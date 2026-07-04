# AGENTS.md

## Project

`parlayBot` is a standalone Python Discord betting bot for a private friend-group server.

It should act like the server's resident degenerate gambler: funny, aggressive, overconfident, and willing to roast bad bets. Keep the tone edgy but safe: no slurs, protected-class insults, real threats, or Discord-rule-breaking harassment.

Primary launch sport: 2026 World Cup soccer.  
Future sports: NFL and UFC.

## Core Build

V1 features:
- Daily 10:00 AM Eastern Discord drop with the day's slate, one straight pick, and one 2-3 leg parlay.
- `/odds [matchup]` for DraftKings/FanDuel consensus odds.
- `/bet [amount] [pick]` to log fake-dollar bets.
- `/resolve [bet_id] [win/loss/push]` for admin bet grading.
- `/leaderboard` ranked strictly by net profit, with a roast for last place.

Architecture:
- Python with `discord.py`.
- SQLite for users, bets, results, and leaderboard state.
- Odds API or OddsPapi free tier for odds.
- Local laptop deployment for now.
- Local Ollama on the laptop for LLM/persona text, using the RTX 3050 4GB GPU when available.

Keep the odds pipeline sport-key based. Do not hard-code World Cup behavior into shared logic. Start with `soccer_fifa_world_cup`, but keep NFL and UFC easy to add.

## Engineering Rules

Build modularly:
- Discord commands/scheduling
- Odds fetching and normalization
- Pick/parlay logic
- LLM/persona generation
- SQLite persistence

The LLM writes personality text only. It must not decide database state, resolve bets, or mutate records.

Never commit secrets, `.env`, API keys, Discord tokens, SQLite runtime DBs, logs, virtualenvs, or cache files.

Use deterministic fallbacks when odds APIs or Ollama are unavailable.

## Git Workflow

Develop directly on `main`.

Make commits throughout development. The git history should look production-grade and easy to review.

Commit whenever a feature is added or materially updated. Use clear commit names based on the work done, for example:
- `Scaffold Discord bot`
- `Add SQLite bet tracking`
- `Implement leaderboard command`
- `Add consensus odds lookup`
- `Wire daily pick drop`
- `Integrate Ollama persona copy`

Do not make one giant final commit unless the user explicitly asks for that.

## Testing

Add focused tests for:
- Odds normalization and consensus lines.
- Parlay odds calculation.
- Bet logging and resolution.
- Push handling.
- Leaderboard sorting by net profit.
- Admin-only resolve behavior.
- Fallbacks for missing odds or unavailable Ollama.

Use mocks for Discord, odds APIs, and LLM calls. Normal tests should not require live external services.

## Source Of Truth

`botPRD.md` contains the original product requirements. If product behavior is unclear or conflicts with this file, ask before changing direction.
