"""Base entity for the Dutch & Dutch integration."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .api import DutchDutchClient, DutchDutchRoom
from .const import DOMAIN


class DutchDutchEntity(Entity):
    """Base entity backed by a Dutch & Dutch room."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, client: DutchDutchClient, room_id: str) -> None:
        self._client = client
        self._room_id = room_id
        room = client.rooms[room_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, room_id)},
            name=room.name,
            manufacturer="Dutch & Dutch",
            model="8c",
            sw_version=room.version,
        )

    @property
    def room(self) -> DutchDutchRoom | None:
        """Return the current room state."""
        return self._client.rooms.get(self._room_id)

    @property
    def available(self) -> bool:
        return self._client.connected and self.room is not None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._client.add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
