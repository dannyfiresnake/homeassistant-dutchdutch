"""Config flow for the Dutch & Dutch integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import CannotConnect, DutchDutchClient, DutchDutchRoom
from .const import DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})


async def _get_room(hass: HomeAssistant, host: str) -> tuple[DutchDutchRoom, str]:
    """Connect to a speaker and return its room and the resolved master host.

    Raises CannotConnect.
    """
    client = DutchDutchClient(host, DEFAULT_PORT, async_get_clientsession(hass))
    try:
        await client.async_connect()
        return next(iter(client.rooms.values())), client.active_host
    finally:
        await client.async_disconnect()


class DutchDutchConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Dutch & Dutch."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._name: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual host entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            try:
                room, master_host = await _get_room(self.hass, host)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating %s", host)
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(room.room_id)
                self._abort_if_unique_id_configured(updates={CONF_HOST: master_host})
                return self.async_create_entry(
                    title=room.name, data={CONF_HOST: master_host}
                )

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle a speaker discovered via mDNS (_x-clerk._tcp)."""
        host = discovery_info.host
        # Both speakers of a pair advertise; don't reconnect to hosts that are
        # already part of a configured entry on every mDNS re-announcement.
        for entry in self._async_current_entries(include_ignore=True):
            if entry.data.get(CONF_HOST) == host:
                return self.async_abort(reason="already_configured")

        try:
            room, master_host = await _get_room(self.hass, host)
        except CannotConnect:
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(room.room_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: master_host})

        self._host = master_host
        self._name = room.name
        self.context["title_placeholders"] = {"name": room.name}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding the discovered room."""
        assert self._host is not None and self._name is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._name, data={CONF_HOST: self._host}
            )

        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={"name": self._name, "host": self._host},
        )
