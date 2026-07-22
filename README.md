# LoL Stats Bot -- Phase 1

A Discord bot that tracks League of Legends ranked stats for a friend group using the Riot Games API.

## Commands

- `!register Name#Tag` -- start tracking a summoner (Riot ID format, e.g. `!register Faker#KR1`)
- `!stats <name>` -- current rank/LP, win rate & KDA over the last 20 ranked games, the last 5 games individually, and all-time top champions
- `!leaderboard` -- ranks all tracked friends by win rate
- `!help` -- shows this command list in Discord

## How the Riot API flow works

Riot IDs (`Name#Tag`) aren't directly usable for match history -- they have to be exchanged for a **PUUID** first:

1. **account-v1**: `Name#Tag` -> PUUID (`/riot/account/v1/accounts/by-riot-id/{name}/{tag}`)
2. **match-v5**: PUUID -> recent Ranked Solo/Duo match IDs only (`/lol/match/v5/matches/by-puuid/{puuid}/ids?queue=420`)
3. **match-v5**: match ID -> full match detail, including every participant's champion/K/D/A/win (`/lol/match/v5/matches/{matchId}`)
4. **summoner-v4**: PUUID -> encrypted summoner ID (`/lol/summoner/v4/summoners/by-puuid/{puuid}`)
5. **league-v4**: summoner ID -> rank entries per queue, including Ranked Solo/Duo tier/division/LP (`/lol/league/v4/entries/by-summoner/{id}`)

Only queue 420 (Ranked Solo/Duo) is tracked -- Flex, normals, ARAM, etc. are filtered out both at the fetch (`queue=420`) and storage/query level, so they never factor into stats or the leaderboard.

Steps 1-3 go to the **europe** *regional* routing host (`europe.api.riotgames.com`); regional routing (europe/americas/asia) is what account-v1 and match-v5 use. Steps 4-5 (rank/LP) go to the **euw1** *platform* routing host (`euw1.api.riotgames.com`) instead -- a different routing concept used by summoner-v4/league-v4. EUW1 belongs to the `europe` regional cluster, which is why this all works for players in Austria; `riot_api.py`'s `RiotClient` talks to both hosts depending on the endpoint.

Fetched matches are cached in SQLite (`match_participations`), keyed by `(match_id, puuid)`. Each `!stats` call only fetches match IDs not already stored, so history accumulates over time instead of being re-fetched (and re-counted against the rate limit) on every call. Rank/LP, being live-changing, is always fetched fresh rather than cached.

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

- `!stats` pulls up to the 20 most recent Ranked Solo/Duo games per call; the win rate/KDA fields use whichever is smaller of the last 20 stored games or however many are stored so far.
- `!leaderboard` only includes summoners who've had `!stats` run at least once -- it reads stored history, it doesn't proactively fetch for everyone. It's also still based on all-time stored win rate, not the last-20 window.
- Champion names are Riot's internal names (e.g. `MonkeyKing` for Wukong).
