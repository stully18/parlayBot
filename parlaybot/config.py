from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    discord_token: str
    discord_guild_id: int | None
    discord_channel_id: int | None
    odds_api_key: str | None
    odds_provider: str
    sport_key: str
    bookmakers: tuple[str, ...]
    ollama_base_url: str
    ollama_model: str
    database_path: str
    timezone: ZoneInfo


def _optional_int(value: str | None) -> int | None:
    if not value:
        return None
    return int(value)


def load_settings() -> Settings:
    load_dotenv()

    bookmakers = tuple(
        item.strip().lower()
        for item in os.getenv("BOOKMAKERS", "draftkings,fanduel").split(",")
        if item.strip()
    )

    return Settings(
        discord_token=os.getenv("DISCORD_TOKEN", ""),
        discord_guild_id=_optional_int(os.getenv("DISCORD_GUILD_ID")),
        discord_channel_id=_optional_int(os.getenv("DISCORD_CHANNEL_ID")),
        odds_api_key=os.getenv("ODDS_API_KEY") or None,
        odds_provider=os.getenv("ODDS_PROVIDER", "the_odds_api"),
        sport_key=os.getenv("SPORT_KEY", "soccer_fifa_world_cup"),
        bookmakers=bookmakers,
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3:8b-instruct-q4_0"),
        database_path=os.getenv("DATABASE_PATH", "./data/parlaybot.sqlite3"),
        timezone=ZoneInfo(os.getenv("TIMEZONE", "America/New_York")),
    )

