"""Buttons: start now (ignore the time window once) and delete the kept originals."""
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ShrinkarrConfigEntry
from .entity import ShrinkarrEntity


async def async_setup_entry(hass: HomeAssistant, entry: ShrinkarrConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    async_add_entities([StartNowButton(coordinator, "start_now"), PurgeKeptButton(coordinator, "purge_kept")])


class StartNowButton(ShrinkarrEntity, ButtonEntity):
    async def async_press(self) -> None:
        await self.coordinator.run(self.coordinator.api.start_now())


class PurgeKeptButton(ShrinkarrEntity, ButtonEntity):
    """Deletes every kept original now; those conversions can no longer be undone."""

    async def async_press(self) -> None:
        await self.coordinator.run(self.coordinator.api.purge_kept())
