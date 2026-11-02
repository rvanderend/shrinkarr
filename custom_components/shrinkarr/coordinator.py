"""Fetches /api/stats every 30 seconds; all entities and the card read from here."""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ShrinkarrApi, ShrinkarrAuthError, ShrinkarrError
from .const import CONF_API_KEY, DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type ShrinkarrConfigEntry = ConfigEntry[ShrinkarrCoordinator]


class ShrinkarrCoordinator(DataUpdateCoordinator[dict]):
    config_entry: ShrinkarrConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ShrinkarrConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.api = ShrinkarrApi(async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_API_KEY])

    async def _async_update_data(self) -> dict:
        try:
            return await self.api.stats()
        except ShrinkarrAuthError as err:
            raise ConfigEntryAuthFailed("The API key is not accepted") from err
        except ShrinkarrError as err:
            raise UpdateFailed(f"Shrinkarr can't be reached: {err}") from err

    async def run(self, call) -> None:
        """Runs an action (pause, purge, ...) and fetches the new state right away."""
        try:
            await call
        except ShrinkarrError as err:
            raise HomeAssistantError(f"Shrinkarr: {err}") from err
        await self.async_refresh()  # right away: request_refresh waits up to 10 s after the last one
