"""Loads secrets and settings from the .env file (never hardcode keys here)."""
import os

from dotenv import load_dotenv

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
RIOT_API_KEY = os.getenv("RIOT_API_KEY")

# account-v1 and match-v5 use *regional* routing (a cluster of platforms),
# not the per-platform routing (e.g. "euw1") used by summoner-v4/league-v4.
# EUW1 belongs to the "europe" regional cluster, so this is what we want
# for Riot ID lookups and match history from Austria.
RIOT_REGION = "europe"

# summoner-v4 and league-v4 (used for current rank/LP) use *platform*
# routing instead -- a single server cluster like "euw1", not the
# "europe" regional cluster above.
RIOT_PLATFORM = "euw1"

DB_PATH = os.getenv("DB_PATH", "lol_stats.db")

if not DISCORD_BOT_TOKEN:
    raise RuntimeError(
        "DISCORD_BOT_TOKEN is not set. Copy .env.example to .env and fill it in."
    )
if not RIOT_API_KEY:
    raise RuntimeError(
        "RIOT_API_KEY is not set. Copy .env.example to .env and fill it in."
    )
