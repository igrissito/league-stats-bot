# LoL Stats Bot -- Phase 1

A Discord bot that tracks League of Legends ranked stats for a friend group using the Riot Games API.

## Commands

- `!register Name#Tag` -- start tracking a summoner (Riot ID format, e.g. `!register Faker#KR1`)
- `!stats <name>` -- recent ranked KDA, win rate, and top champions
- `!leaderboard` -- ranks all tracked friends by win rate

## How the Riot API flow works

Riot IDs (`Name#Tag`) aren't directly usable for match history -- they have to be exchanged for a **PUUID** first:

1. **account-v1**: `Name#Tag` -> PUUID (`/riot/account/v1/accounts/by-riot-id/{name}/{tag}`)
2. **match-v5**: PUUID -> recent ranked match IDs (`/lol/match/v5/matches/by-puuid/{puuid}/ids?type=ranked`)
3. **match-v5**: match ID -> full match detail, including every participant's champion/K/D/A/win (`/lol/match/v5/matches/{matchId}`)

All three calls go to the **europe** *regional* routing host (`europe.api.riotgames.com`), not a per-platform host like `euw1`. Regional routing (europe/americas/asia) is what account-v1 and match-v5 use; platform routing (euw1, na1, ...) is a separate concept used by other endpoints (summoner-v4, league-v4) that this Phase 1 bot doesn't need. EUW1 (Europe West) belongs to the `europe` regional cluster, which is why this works for players in Austria.

Fetched matches are cached in SQLite (`match_participations`), keyed by `(match_id, puuid)`. Each `!stats` call only fetches match IDs not already stored, so history accumulates over time instead of being re-fetched (and re-counted against the rate limit) on every call.

## Setup

### 1. Get a Discord bot token

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) -> **New Application**.
2. **Bot** tab -> **Reset Token** -> copy it.
3. Still on the Bot tab, under **Privileged Gateway Intents**, enable **Message Content Intent** (required -- commands are read from the raw message text).
4. **OAuth2 -> URL Generator**: scope `bot`, permissions `Send Messages`, `Embed Links`, `Read Message History`. Open the generated URL to invite the bot to your server.

### 2. Get a Riot API key

1. Go to the [Riot Developer Portal](https://developer.riotgames.com/) and log in with your Riot account.
2. Generate a **development API key** from the dashboard.
3. **Development keys expire every 24 hours.** You'll need to regenerate it and update `.env` each day you work on this. (A production key requires an approved application and doesn't expire this way.)

### 3. Configure environment

```
copy .env.example .env
```

Fill in `.env`:

```
DISCORD_BOT_TOKEN=your-discord-bot-token
RIOT_API_KEY=your-riot-api-key
```

`.env` is gitignored -- never commit real keys. `.env.example` stays committed as documentation with empty values.

### 4. Install and run (Windows, `py` launcher)

```
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
py bot.py
```

## Data storage

`lol_stats.db` (SQLite) is created next to `bot.py` on first run. It's gitignored -- it's accumulated local history, not source code.

## Rate limiting

`riot_api.py` self-throttles to stay under personal dev-key limits (20 requests/1s, 100 requests/2min) before sending requests, and additionally backs off on real HTTP 429 responses using the `Retry-After` header. A 401/403 from Riot is treated as a likely expired/invalid key and surfaces a clear error instead of a raw stack trace.

## Known Phase 1 limitations

- `!stats` pulls up to the 10 most recent ranked games per call (both solo/duo and flex combined, no queue split).
- `!leaderboard` only includes summoners who've had `!stats` run at least once -- it reads stored history, it doesn't proactively fetch for everyone.
- Champion names are Riot's internal names (e.g. `MonkeyKing` for Wukong).
