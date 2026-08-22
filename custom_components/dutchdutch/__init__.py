"""The Dutch & Dutch integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CannotConnect, DutchDutchClient
from .const import DEFAULT_PORT

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.SELECT, Platform.SWITCH]

type DutchDutchConfigEntry = ConfigEntry[DutchDutchClient]


async def async_setup_entry(hass: HomeAssistant, entry: DutchDutchConfigEntry) -> bool:
    """Set up Dutch & Dutch from a config entry."""
    client = DutchDutchClient(
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
        async_get_clientsession(hass),
    )
    try:
        await client.async_connect()
    except CannotConnect as err:
        raise ConfigEntryNotReady(
            f"Cannot connect to Dutch & Dutch at {entry.data[CONF_HOST]}"
        ) from err

    entry.runtime_data = client
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DutchDutchConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await entry.runtime_data.async_disconnect()
    return unload_ok
