"""Hoardo Homebox Import."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import HomeboxClient, HomeboxError
from .const import CONF_ROOM, DOMAIN, SERVICE_IMPORT_CSV, STORAGE_VERSION
from .importer import async_import

_LOGGER = logging.getLogger(__name__)

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("path"): cv.string,
        vol.Required(CONF_ROOM): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)


async def run_import(hass: HomeAssistant, entry: ConfigEntry, csv_text: str, room: str) -> None:
    """Run an import and report the outcome as a persistent notification."""
    lock: asyncio.Lock = hass.data[DOMAIN]["locks"].setdefault(entry.entry_id, asyncio.Lock())
    if lock.locked():
        persistent_notification.async_create(
            hass, "An import is already running.", "Hoardo import", f"{DOMAIN}_{entry.entry_id}"
        )
        return
    async with lock:
        client = HomeboxClient(
            async_get_clientsession(hass),
            entry.data[CONF_URL],
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
        )
        store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        try:
            res = await async_import(hass, client, store, csv_text, room)
        except HomeboxError as err:
            msg = f"Import stopped: {err}"
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Unexpected import error")
            msg = f"Import crashed: {err}"
        else:
            msg = (
                f"Imported {res['imported']}, already done {res['skipped']}, "
                f"failed {res['failed']}."
            )
            if res["photos_retried"]:
                msg += f"\nRecovered {res['photos_retried']} previously missing photo(s)."
            if res["photo_failed"]:
                msg += f"\nPhoto upload/retry failed for {res['photo_failed']} item(s)."
            if res["photo_fallbacks"]:
                msg += (
                    f"\n{res['photo_fallbacks']} photo(s) uploaded in their original format "
                    "(conversion unavailable)."
                )
            if res["errors"]:
                msg += "\n\n" + "\n".join(res["errors"][:10])
        persistent_notification.async_create(
            hass, msg, f"Hoardo import: {room}", f"{DOMAIN}_{entry.entry_id}"
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {"locks": {}})

    async def handle_import(call: ServiceCall) -> None:
        entries = hass.config_entries.async_entries(DOMAIN)
        wanted = call.data.get("config_entry_id")
        if wanted:
            entries = [e for e in entries if e.entry_id == wanted]
        if len(entries) != 1:
            raise ServiceValidationError("Specify config_entry_id when more than one Homebox is configured.")
        path = call.data["path"]
        if not hass.config.is_allowed_path(path):
            raise ServiceValidationError(f"Path not allowed: {path}. Use /config or add it to allowlist_external_dirs.")
        try:
            text = await hass.async_add_executor_job(Path(path).read_text, "utf-8-sig")
        except OSError as err:
            raise HomeAssistantError(f"Cannot read {path}: {err}") from err
        entries[0].async_create_background_task(
            hass, run_import(hass, entries[0], text, call.data[CONF_ROOM]), f"{DOMAIN}_import"
        )

    if not hass.services.has_service(DOMAIN, SERVICE_IMPORT_CSV):
        hass.services.async_register(DOMAIN, SERVICE_IMPORT_CSV, handle_import, schema=SERVICE_SCHEMA)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if len(hass.config_entries.async_entries(DOMAIN)) <= 1:
        hass.services.async_remove(DOMAIN, SERVICE_IMPORT_CSV)
    return True
