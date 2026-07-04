# parlayBot

Standalone Python Discord betting bot for a private friend-group server. V1 targets local desktop development, then laptop runtime with local Ollama.

The bot tracks fake-dollar bets, serves DraftKings/FanDuel consensus odds, posts a 10:00 AM Eastern daily drop, and keeps a net-profit leaderboard.

## Local Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:

```env
DISCORD_TOKEN=your-discord-bot-token
DISCORD_GUILD_ID=your-test-server-id
DISCORD_CHANNEL_ID=channel-for-daily-drops
ODDS_API_KEY=your-odds-api-key
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3:8b-instruct-q4_0
```

`DISCORD_GUILD_ID` is optional but recommended during development because slash commands sync faster to one test server.

## Run

```bash
./.venv/bin/python -m parlaybot
```

The SQLite database is created at `./data/parlaybot.sqlite3` by default. Runtime databases, logs, virtualenvs, caches, and secrets are ignored by git.

Before starting the bot, validate local config and initialize the database:

```bash
./.venv/bin/python -m parlaybot --check-config
./.venv/bin/python -m parlaybot --init-db
```

`--check-config` requires `DISCORD_TOKEN` for a clean pass. It warns, but does not fail, when `ODDS_API_KEY` is missing because the bot has fallback copy for unavailable odds.

## Test

```bash
./.venv/bin/python -m pytest
```

Tests mock or isolate Discord, odds APIs, and Ollama. They should not require live external services.

## Commands

- `/odds matchup`: fetches DraftKings/FanDuel consensus moneyline odds for the configured sport.
- `/bet amount pick`: logs a fake-dollar pending bet.
- `/resolve bet_id result`: admin-only grading for `win`, `loss`, or `push`.
- `/leaderboard`: ranks users strictly by net profit and roasts last place.
- `/dropnow`: admin-only command to post the daily drop immediately. Use this for same-day launch or testing after 10:00 AM Eastern.

## Config

- `SPORT_KEY` defaults to `soccer_fifa_world_cup`.
- `BOOKMAKERS` defaults to `draftkings,fanduel`.
- `TIMEZONE` defaults to `America/New_York`.
- `DATABASE_PATH` defaults to `./data/parlaybot.sqlite3`.

Change `SPORT_KEY` later for NFL or UFC without rewriting the odds pipeline.
