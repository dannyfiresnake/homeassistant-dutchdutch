"""Switch entities for Dutch & Dutch rooms (linear phase)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DutchDutchConfigEntry
from .api import DutchDutchClient
from .entity import DutchDutchEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DutchDutchConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches for each room on this connection."""
    client = entry.runtime_data
    async_add_entities(
        DutchDutchLinearPhaseSwitch(client, room_id) for room_id in client.rooms
    )


class DutchDutchLinearPhaseSwitch(DutchDutchEntity, SwitchEntity):
    """Toggles the linear phase crossover filters."""

    _attr_translation_key = "linear_phase"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, client: DutchDutchClient, room_id: str) -> None:
        super().__init__(client, room_id)
        self._attr_unique_id = f"{room_id}-linear_phase"

    @property
    def is_on(self) -> bool | None:
        room = self.room
        return room.linear_phase if room else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._client.async_set_linear_phase(self._room_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.async_set_linear_phase(self._room_id, False)
