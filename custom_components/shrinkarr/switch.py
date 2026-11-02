"""The queue switch: off = paused (the running conversion still finishes)."""
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ShrinkarrConfigEntry
from .entity import ShrinkarrEntity


async def async_setup_entry(hass: HomeAssistant, entry: ShrinkarrConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([QueueSwitch(entry.runtime_data, "queue_running")])


class QueueSwitch(ShrinkarrEntity, SwitchEntity):
    @property
    def is_on(self) -> bool:
        return not self.coordinator.data["queue"]["paused"]

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.run(self.coordinator.api.set_paused(False))

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.run(self.coordinator.api.set_paused(True))
