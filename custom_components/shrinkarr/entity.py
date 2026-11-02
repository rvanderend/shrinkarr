"""Base entity: one Shrinkarr device per config entry."""
from homeassistant.const import CONF_URL
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ShrinkarrCoordinator


class ShrinkarrEntity(CoordinatorEntity[ShrinkarrCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ShrinkarrCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name="Shrinkarr", manufacturer="Shrinkarr",
            sw_version=coordinator.data.get("version"), configuration_url=entry.data[CONF_URL],
            entry_type=DeviceEntryType.SERVICE,
        )
