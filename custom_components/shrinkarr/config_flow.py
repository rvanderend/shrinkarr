"""Set up Shrinkarr with its address and API key; asks for a new key when it stops working."""
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ShrinkarrApi, ShrinkarrAuthError, ShrinkarrError, ShrinkarrTooOld
from .const import CONF_API_KEY, DOMAIN

USER_SCHEMA = vol.Schema({vol.Required(CONF_URL): str, vol.Required(CONF_API_KEY): str})
KEY_SCHEMA = vol.Schema({vol.Required(CONF_API_KEY): str})


def _clean_url(url: str) -> str:
    url = url.strip().rstrip("/")
    return url if url.startswith(("http://", "https://")) else "http://" + url


class ShrinkarrConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _check(self, url: str, key: str) -> dict[str, str]:
        try:
            await ShrinkarrApi(async_get_clientsession(self.hass), url, key).check_key()
        except ShrinkarrAuthError:
            return {"base": "invalid_auth"}
        except ShrinkarrTooOld:
            return {"base": "too_old"}
        except ShrinkarrError:
            return {"base": "cannot_connect"}
        return {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url, key = _clean_url(user_input[CONF_URL]), user_input[CONF_API_KEY].strip()
            self._async_abort_entries_match({CONF_URL: url})
            errors = await self._check(url, key)
            if not errors:
                return self.async_create_entry(title="Shrinkarr", data={CONF_URL: url, CONF_API_KEY: key})
        return self.async_show_form(step_id="user", data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
                                    errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            key = user_input[CONF_API_KEY].strip()
            errors = await self._check(entry.data[CONF_URL], key)
            if not errors:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_API_KEY: key})
        return self.async_show_form(step_id="reauth_confirm", data_schema=KEY_SCHEMA, errors=errors,
                                    description_placeholders={"url": entry.data[CONF_URL]})
