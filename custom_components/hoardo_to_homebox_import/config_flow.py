"""Config + options flow for Hoardo Import."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    FileSelector,
    FileSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import HomeboxAuthError, HomeboxClient, HomeboxError
from .const import CONF_ROOM, DOMAIN


class HoardoConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = HomeboxClient(
                async_get_clientsession(self.hass),
                user_input[CONF_URL],
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            try:
                await client.login()
            except HomeboxAuthError:
                errors["base"] = "invalid_auth"
            except HomeboxError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(user_input[CONF_URL].rstrip("/"))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Homebox (Hoardo import)", data=user_input)
        schema = vol.Schema(
            {
                vol.Required(CONF_URL, default=(user_input or {}).get(CONF_URL, "http://")): str,
                vol.Required(CONF_USERNAME, default=(user_input or {}).get(CONF_USERNAME, "")): str,
                vol.Required(CONF_PASSWORD): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return HoardoOptionsFlow()


class HoardoOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            from . import run_import  # local import avoids a cycle at load time

            def _read() -> str:
                with process_uploaded_file(self.hass, user_input["file"]) as path:
                    return path.read_text("utf-8-sig")

            text = await self.hass.async_add_executor_job(_read)
            room = user_input[CONF_ROOM].strip()
            self.config_entry.async_create_background_task(
                self.hass, run_import(self.hass, self.config_entry, text, room), f"{DOMAIN}_import"
            )
            return self.async_create_entry(title="", data=dict(self.config_entry.options))
        schema = vol.Schema(
            {
                vol.Required("file"): FileSelector(FileSelectorConfig(accept=".csv,text/csv")),
                vol.Required(CONF_ROOM): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
