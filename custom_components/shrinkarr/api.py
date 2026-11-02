"""A small client for the Shrinkarr API."""
import asyncio

import aiohttp


class ShrinkarrError(Exception):
    """Shrinkarr can't be reached or gave an error."""


class ShrinkarrAuthError(ShrinkarrError):
    """The API key is wrong."""


class ShrinkarrTooOld(ShrinkarrError):
    """This Shrinkarr has no API key yet (before 1.0.4)."""


class ShrinkarrApi:
    def __init__(self, session: aiohttp.ClientSession, url: str, api_key: str) -> None:
        self.url = url.rstrip("/")
        self._session = session
        self._key = api_key

    async def _request(self, method: str, path: str, json: dict | None = None):
        try:
            async with self._session.request(
                method, self.url + path, json=json, headers={"X-Api-Key": self._key},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 401:
                    raise ShrinkarrAuthError
                if resp.status == 404:
                    raise ShrinkarrTooOld
                resp.raise_for_status()
                return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ShrinkarrError(str(err) or type(err).__name__) from err

    async def check_key(self) -> None:
        """Raises ShrinkarrAuthError when the key is wrong, also when the login is off
        (then every call works, so the key is compared with the one Shrinkarr has)."""
        if (await self._request("GET", "/api/apikey"))["key"] != self._key:
            raise ShrinkarrAuthError

    async def stats(self) -> dict:
        return await self._request("GET", "/api/stats")

    async def set_paused(self, paused: bool) -> None:
        await self._request("PUT", "/api/settings", {"paused": paused})

    async def start_now(self) -> None:
        await self._request("POST", "/api/queue/start-now")

    async def purge_kept(self) -> None:
        await self._request("POST", "/api/kept/purge")
