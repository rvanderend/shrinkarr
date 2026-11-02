"""Shrinkarr for Home Assistant: sensors, controls and a dashboard card."""
from pathlib import Path

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import CARD_URL, DOMAIN
from .coordinator import ShrinkarrConfigEntry, ShrinkarrCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR, Platform.SWITCH]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    # The card ships with the integration: no separate download or dashboard resource needed.
    version = (await async_get_integration(hass, DOMAIN)).version
    path = Path(__file__).parent / "frontend" / "shrinkarr-card.js"
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(path), False)])
    add_extra_js_url(hass, f"{CARD_URL}?v={version}")
    websocket_api.async_register_command(hass, ws_subscribe)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ShrinkarrConfigEntry) -> bool:
    coordinator = ShrinkarrCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ShrinkarrConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


@websocket_api.websocket_command({vol.Required("type"): "shrinkarr/subscribe", vol.Optional("entry_id"): str})
@callback
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """For the card: the whole /api/stats response on every update, plus the entity ids of the controls."""
    entries = [e for e in hass.config_entries.async_entries(DOMAIN)
               if e.state is ConfigEntryState.LOADED and msg.get("entry_id") in (None, e.entry_id)]
    if not entries:
        connection.send_error(msg["id"], "not_found", "Shrinkarr is not set up")
        return
    entry = entries[0]
    coordinator: ShrinkarrCoordinator = entry.runtime_data
    prefix = entry.entry_id + "_"

    @callback
    def send() -> None:
        entities = {e.unique_id.removeprefix(prefix): e.entity_id
                    for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}
        connection.send_message(websocket_api.event_message(msg["id"], {
            "url": entry.data[CONF_URL], "available": coordinator.last_update_success,
            "data": coordinator.data, "entities": entities,
        }))

    connection.subscriptions[msg["id"]] = coordinator.async_add_listener(send)
    connection.send_result(msg["id"])
    send()
