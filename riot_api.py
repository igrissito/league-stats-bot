"""Async Riot Games API client: Riot ID -> PUUID -> match history.

Flow used by this bot:
  1. account-v1  (by-riot-id)   "Name#Tag"      -> puuid
  2. match-v5    (by-puuid/ids) puuid           -> list of recent Ranked Solo/Duo match IDs (queue=420)
  3. match-v5    (matches/{id}) match id         -> full match detail (all 10 participants)

Steps 1-3 all use *regional* routing (europe/americas/asia), which is a
different concept from the per-platform routing (euw1, na1, ...) used by
endpoints like summoner-v4/league-v4. EUW1 sits in the "europe" region,
which is what this bot is configured for.
"""
import asyncio
import time
from collections import deque
from urllib.parse import quote

import aiohttp

# Riot's queue ID for Ranked Solo/Duo (as opposed to 440 for Ranked Flex,
# etc.) -- https://static.developer.riotgames.com/docs/lol/queues.json
SOLO_DUO_QUEUE_ID = 420


class RiotAPIError(Exception):
    """Raised for non-recoverable Riot API responses (auth, bad request, etc.)."""


class RateLimiter:
    """Client-side throttle for a personal *development* API key.

    Default dev key limits are 20 requests/1s and 100 requests/2min. Rather
    than firing requests and hoping, we track recent request timestamps and
    make the caller `await` until there's headroom in both windows. This
    doesn't replace handling real 429s (something else could share the key,
    or Riot could tighten limits) — see the 429 handling in RiotClient._get.
    """

    def __init__(self, short_limit=20, short_window=1.0, long_limit=100, long_window=120.0):
        self.short_limit = short_limit
        self.short_window = short_window
        self.long_limit = long_limit
        self.long_window = long_window
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] > self.long_window:
                    self._timestamps.popleft()

                recent_short = [t for t in self._timestamps if now - t <= self.short_window]

                if len(self._timestamps) < self.long_limit and len(recent_short) < self.short_limit:
                    self._timestamps.append(now)
                    return

                wait_candidates = []
                if len(recent_short) >= self.short_limit:
                    wait_candidates.append(self.short_window - (now - recent_short[0]))
                if len(self._timestamps) >= self.long_limit:
                    wait_candidates.append(self.long_window - (now - self._timestamps[0]))
                await asyncio.sleep(max(wait_candidates) + 0.01)


class RiotClient:
    def __init__(self, api_key: str, region: str = "europe"):
        self._headers = {"X-Riot-Token": api_key}
        self._base_url = f"https://{region}.api.riotgames.com"
        self._session: aiohttp.ClientSession | None = None
        self._rate_limiter = RateLimiter()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get(self, url: str, params: dict | None = None) -> dict | list | None:
        session = await self._get_session()
        for _ in range(3):
            await self._rate_limiter.acquire()
            async with session.get(url, headers=self._headers, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
                if resp.status == 404:
                    return None
                if resp.status == 429:
                    retry_after = float(resp.headers.get("Retry-After", "1"))
                    await asyncio.sleep(retry_after + 0.5)
                    continue
                if resp.status in (401, 403):
                    raise RiotAPIError(
                        f"Riot API auth error ({resp.status}). Check RIOT_API_KEY in .env — "
                        "personal dev keys expire every 24h and need regenerating."
                    )
                text = await resp.text()
                raise RiotAPIError(f"Riot API error {resp.status}: {text[:200]}")
        raise RiotAPIError("Riot API kept rate-limiting us (429) after 3 retries. Try again shortly.")

    async def get_puuid_by_riot_id(self, game_name: str, tag_line: str) -> str | None:
        url = f"{self._base_url}/riot/account/v1/accounts/by-riot-id/{quote(game_name)}/{quote(tag_line)}"
        data = await self._get(url)
        return data["puuid"] if data else None

    async def get_solo_duo_match_ids(self, puuid: str, count: int = 10) -> list[str]:
        """Recent Ranked Solo/Duo match IDs only (queue=420 filters server-side)."""
        url = f"{self._base_url}/lol/match/v5/matches/by-puuid/{puuid}/ids"
        params = {"queue": SOLO_DUO_QUEUE_ID, "start": 0, "count": count}
        data = await self._get(url, params=params)
        return data or []

    async def get_match(self, match_id: str) -> dict | None:
        url = f"{self._base_url}/lol/match/v5/matches/{quote(match_id)}"
        return await self._get(url)
