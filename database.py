"""SQLite storage: tracked summoners + accumulated match history.

Two tables:
- summoners: one row per friend registered with !register.
- match_participations: one row per (match, summoner) we've fetched. This is
  the accumulation layer — !stats only asks Riot for new match IDs each time
  and skips ones already stored, so history builds up over repeated calls
  instead of being re-fetched (and re-counted against the rate limit) daily.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from config import DB_PATH
from riot_api import SOLO_DUO_QUEUE_ID

SCHEMA = """
CREATE TABLE IF NOT EXISTS summoners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    riot_id TEXT NOT NULL UNIQUE,      -- "Name#Tag" exactly as registered
    game_name TEXT NOT NULL,
    tag_line TEXT NOT NULL,
    puuid TEXT NOT NULL UNIQUE,
    registered_by TEXT,                -- Discord user id who ran !register
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS match_participations (
    match_id TEXT NOT NULL,
    puuid TEXT NOT NULL,
    champion TEXT NOT NULL,
    kills INTEGER NOT NULL,
    deaths INTEGER NOT NULL,
    assists INTEGER NOT NULL,
    win INTEGER NOT NULL,              -- 0/1
    queue_id INTEGER NOT NULL,
    game_creation INTEGER NOT NULL,    -- epoch ms, from Riot
    stored_at TEXT NOT NULL,
    PRIMARY KEY (match_id, puuid)
);
"""


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        conn.executescript(SCHEMA)


def add_summoner(riot_id: str, game_name: str, tag_line: str, puuid: str, registered_by: str) -> bool:
    """Returns False (no-op) if this riot_id or puuid is already tracked."""
    with get_connection() as conn:
        try:
            conn.execute(
                """INSERT INTO summoners (riot_id, game_name, tag_line, puuid, registered_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (riot_id, game_name, tag_line, puuid, registered_by, datetime.now(timezone.utc).isoformat()),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def find_summoner(name: str):
    """Look up a tracked summoner by exact 'Name#Tag' or partial name match."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM summoners WHERE LOWER(riot_id) = ? OR LOWER(game_name) LIKE ? LIMIT 1",
            (name.lower(), f"%{name.lower()}%"),
        ).fetchone()


def list_summoners():
    with get_connection() as conn:
        return conn.execute("SELECT * FROM summoners").fetchall()


def match_exists(match_id: str, puuid: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM match_participations WHERE match_id = ? AND puuid = ?",
            (match_id, puuid),
        ).fetchone()
        return row is not None


def save_match_participation(match_id, puuid, champion, kills, deaths, assists, win, queue_id, game_creation):
    with get_connection() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO match_participations
               (match_id, puuid, champion, kills, deaths, assists, win, queue_id, game_creation, stored_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                match_id, puuid, champion, kills, deaths, assists, int(win), queue_id, game_creation,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def get_summoner_summary(puuid: str):
    """Returns (totals_row, top_champions_rows) aggregated from stored Ranked Solo/Duo matches."""
    with get_connection() as conn:
        totals = conn.execute(
            """SELECT COUNT(*) AS games, SUM(win) AS wins,
                      SUM(kills) AS k, SUM(deaths) AS d, SUM(assists) AS a
               FROM match_participations WHERE puuid = ? AND queue_id = ?""",
            (puuid, SOLO_DUO_QUEUE_ID),
        ).fetchone()
        champs = conn.execute(
            """SELECT champion, COUNT(*) AS games, SUM(win) AS wins
               FROM match_participations WHERE puuid = ? AND queue_id = ?
               GROUP BY champion ORDER BY games DESC LIMIT 3""",
            (puuid, SOLO_DUO_QUEUE_ID),
        ).fetchall()
        return totals, champs


def get_leaderboard(min_games: int = 1):
    """Tracked summoners ranked by Ranked Solo/Duo win rate, using whatever history is stored."""
    with get_connection() as conn:
        return conn.execute(
            """SELECT s.riot_id AS riot_id,
                      COUNT(m.match_id) AS games,
                      SUM(m.win) AS wins
               FROM summoners s
               JOIN match_participations m ON m.puuid = s.puuid
               WHERE m.queue_id = ?
               GROUP BY s.puuid
               HAVING games >= ?
               ORDER BY (CAST(wins AS FLOAT) / games) DESC, games DESC""",
            (SOLO_DUO_QUEUE_ID, min_games),
        ).fetchall()
