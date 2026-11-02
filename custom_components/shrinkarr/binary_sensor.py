"""Binary sensors: failed conversions and whether the GPU is encoding."""
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ShrinkarrConfigEntry
from .entity import ShrinkarrEntity


async def async_setup_entry(hass: HomeAssistant, entry: ShrinkarrConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([FailedSensor(entry.runtime_data, "failed"), EncodingSensor(entry.runtime_data, "encoding")])


class FailedSensor(ShrinkarrEntity, BinarySensorEntity):
    """On while the history has failed jobs (until they are retried or cleared in Shrinkarr)."""
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool:
        return self.coordinator.data["queue"]["failed"] > 0

    @property
    def extra_state_attributes(self) -> dict:
        return {"count": self.coordinator.data["queue"]["failed"]}


class EncodingSensor(ShrinkarrEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def is_on(self) -> bool:
        return self.coordinator.data["gpu"]["encoding"]
