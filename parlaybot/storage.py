from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


VALID_RESULTS = {"win", "loss", "push"}
PENDING = "pending"


@dataclass(frozen=True)
class Bet:
    id: int
    user_id: int
    username: str
    amount: float
    pick: str
    odds: int | None
    status: str
    result: str | None
    profit: float
    created_at: str
    resolved_at: str | None


@dataclass(frozen=True)
class LeaderboardEntry:
    user_id: int
    username: str
    net_profit: float
    amount_wagered: float
    wins: int
    losses: int
    pushes: int
    pending: int


class BetStore:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        path = Path(self.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    amount REAL NOT NULL CHECK (amount > 0),
                    pick TEXT NOT NULL,
                    odds INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result TEXT,
                    profit REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS daily_drops (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    drop_date TEXT NOT NULL,
                    sport_key TEXT NOT NULL,
                    channel_id INTEGER,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def log_bet(self, user_id: int, username: str, amount: float, pick: str, odds: int | None = None) -> Bet:
        if amount <= 0:
            raise ValueError("Bet amount must be positive")
        clean_pick = pick.strip()
        if not clean_pick:
            raise ValueError("Pick cannot be empty")

        now = _now()
        with self._connect() as conn:
            self._upsert_user(conn, user_id, username, now)
            cursor = conn.execute(
                """
                INSERT INTO bets (user_id, username, amount, pick, odds, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, username, amount, clean_pick, odds, now),
            )
            bet_id = int(cursor.lastrowid)
            return self.get_bet(bet_id, conn=conn)

    def resolve_bet(self, bet_id: int, result: str) -> Bet:
        if result not in VALID_RESULTS:
            raise ValueError("Result must be win, loss, or push")

        with self._connect() as conn:
            bet = self.get_bet(bet_id, conn=conn)
            if bet.status != PENDING:
                raise ValueError(f"Bet {bet_id} has already been resolved")

            profit = _profit_for_result(bet.amount, bet.odds, result)
            resolved_at = _now()
            conn.execute(
                """
                UPDATE bets
                SET status = 'resolved', result = ?, profit = ?, resolved_at = ?
                WHERE id = ?
                """,
                (result, profit, resolved_at, bet_id),
            )
            return self.get_bet(bet_id, conn=conn)

    def get_bet(self, bet_id: int, conn: sqlite3.Connection | None = None) -> Bet:
        owns_connection = conn is None
        active = conn or self._connect()
        try:
            row = active.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
            if row is None:
                raise KeyError(f"Bet {bet_id} not found")
            return _row_to_bet(row)
        finally:
            if owns_connection:
                active.close()

    def leaderboard(self) -> list[LeaderboardEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    user_id,
                    COALESCE(MAX(username), 'unknown') AS username,
                    COALESCE(SUM(profit), 0) AS net_profit,
                    COALESCE(SUM(CASE WHEN status = 'resolved' THEN amount ELSE 0 END), 0) AS amount_wagered,
                    SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END) AS losses,
                    SUM(CASE WHEN result = 'push' THEN 1 ELSE 0 END) AS pushes,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending
                FROM bets
                GROUP BY user_id
                ORDER BY net_profit DESC, wins DESC, amount_wagered ASC
                """
            ).fetchall()
        return [
            LeaderboardEntry(
                user_id=int(row["user_id"]),
                username=str(row["username"]),
                net_profit=float(row["net_profit"]),
                amount_wagered=float(row["amount_wagered"]),
                wins=int(row["wins"]),
                losses=int(row["losses"]),
                pushes=int(row["pushes"]),
                pending=int(row["pending"]),
            )
            for row in rows
        ]

    def record_daily_drop(self, drop_date: str, sport_key: str, channel_id: int | None, content: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO daily_drops (drop_date, sport_key, channel_id, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (drop_date, sport_key, channel_id, content, _now()),
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _upsert_user(conn: sqlite3.Connection, user_id: int, username: str, now: str) -> None:
        conn.execute(
            """
            INSERT INTO users (user_id, username, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username = excluded.username, updated_at = excluded.updated_at
            """,
            (user_id, username, now),
        )


def _profit_for_result(amount: float, odds: int | None, result: str) -> float:
    if result == "push":
        return 0.0
    if result == "loss":
        return -amount
    if odds is None:
        return amount
    if odds > 0:
        return round(amount * odds / 100, 2)
    return round(amount * 100 / abs(odds), 2)


def _row_to_bet(row: sqlite3.Row) -> Bet:
    return Bet(
        id=int(row["id"]),
        user_id=int(row["user_id"]),
        username=str(row["username"]),
        amount=float(row["amount"]),
        pick=str(row["pick"]),
        odds=int(row["odds"]) if row["odds"] is not None else None,
        status=str(row["status"]),
        result=str(row["result"]) if row["result"] is not None else None,
        profit=float(row["profit"]),
        created_at=str(row["created_at"]),
        resolved_at=str(row["resolved_at"]) if row["resolved_at"] is not None else None,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()

