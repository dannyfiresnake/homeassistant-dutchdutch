"""Select entities for Dutch & Dutch rooms (XLR mode, preset)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
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
    """Set up selects for each room on this connection."""
    client = entry.runtime_data
    entities: list[SelectEntity] = []
    for room_id, room in client.rooms.items():
        if room.input_modes:
            entities.append(DutchDutchInputSelect(client, room_id))
        if room.xlr_modes:
            entities.append(DutchDutchXlrModeSelect(client, room_id))
        if room.presets:
            entities.append(DutchDutchPresetSelect(client, room_id))
    async_add_entities(entities)


class DutchDutchInputSelect(DutchDutchEntity, SelectEntity):
    """Selects the active input source (mirrors the media player source)."""

    _attr_translation_key = "input"

    def __init__(self, client: DutchDutchClient, room_id: str) -> None:
        super().__init__(client, room_id)
        self._attr_unique_id = f"{room_id}-input"

    @property
    def options(self) -> list[str]:
        room = self.room
        return room.input_modes if room else []

    @property
    def current_option(self) -> str | None:
        room = self.room
        return room.selected_input if room else None

    async def async_select_option(self, option: str) -> None:
        await self._client.async_set_input(self._room_id, option)


class DutchDutchXlrModeSelect(DutchDutchEntity, SelectEntity):
    """Selects the physical XLR input mode (AES / analog gain)."""

    _attr_translation_key = "xlr_mode"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, client: DutchDutchClient, room_id: str) -> None:
        super().__init__(client, room_id)
        self._attr_unique_id = f"{room_id}-xlr_mode"

    @property
    def options(self) -> list[str]:
        room = self.room
        return room.xlr_modes if room else []

    @property
    def current_option(self) -> str | None:
        room = self.room
        return room.selected_xlr if room else None

    async def async_select_option(self, option: str) -> None:
        await self._client.async_set_xlr_mode(self._room_id, option)


class DutchDutchPresetSelect(DutchDutchEntity, SelectEntity):
    """Selects a room preset."""

    _attr_translation_key = "preset"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, client: DutchDutchClient, room_id: str) -> None:
        super().__init__(client, room_id)
        self._attr_unique_id = f"{room_id}-preset"

    @property
    def options(self) -> list[str]:
        room = self.room
        return list(room.presets.values()) if room else []

    @property
    def current_option(self) -> str | None:
        room = self.room
        if room is None or room.selected_preset is None:
            return None
        return room.presets.get(room.selected_preset)

    async def async_select_option(self, option: str) -> None:
        room = self.room
        if room is None:
            return
        for preset_id, name in room.presets.items():
            if name == option:
                await self._client.async_select_preset(self._room_id, preset_id)
                return
