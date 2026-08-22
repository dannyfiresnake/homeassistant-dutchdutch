"""Media player entity for Dutch & Dutch rooms."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DutchDutchConfigEntry
from .api import DutchDutchClient
from .entity import DutchDutchEntity

BASE_FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.SELECT_SOUND_MODE
)

# dB per volume_up/volume_down press.
VOLUME_STEP_DB = 1.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DutchDutchConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up media players for each room on this connection."""
    client = entry.runtime_data
    async_add_entities(
        DutchDutchMediaPlayer(client, room_id) for room_id in client.rooms
    )


class DutchDutchMediaPlayer(DutchDutchEntity, MediaPlayerEntity):
    """Media player for a Dutch & Dutch room."""

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_media_content_type = MediaType.MUSIC

    def __init__(self, client: DutchDutchClient, room_id: str) -> None:
        super().__init__(client, room_id)
        self._attr_unique_id = room_id

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        features = BASE_FEATURES
        room = self.room
        methods = room.streaming.methods if room and room.streaming else {}
        if methods.get("play") or methods.get("playPause"):
            features |= MediaPlayerEntityFeature.PLAY
        if methods.get("pause") or methods.get("playPause"):
            features |= MediaPlayerEntityFeature.PAUSE
        if methods.get("next"):
            features |= MediaPlayerEntityFeature.NEXT_TRACK
        if methods.get("previous") or methods.get("prev"):
            features |= MediaPlayerEntityFeature.PREVIOUS_TRACK
        return features

    @property
    def state(self) -> MediaPlayerState:
        room = self.room
        if room is None:
            return MediaPlayerState.OFF
        if room.sleep:
            return MediaPlayerState.STANDBY
        if room.streaming is not None:
            if room.streaming.is_playing:
                return MediaPlayerState.PLAYING
            if room.streaming.display:
                return MediaPlayerState.PAUSED
        return MediaPlayerState.IDLE

    # ---------- Volume ----------

    @property
    def volume_level(self) -> float | None:
        room = self.room
        if room is None or room.gain_max <= room.gain_min:
            return None
        level = (room.gain - room.gain_min) / (room.gain_max - room.gain_min)
        return max(0.0, min(1.0, level))

    @property
    def is_volume_muted(self) -> bool | None:
        room = self.room
        return room.muted if room else None

    async def async_set_volume_level(self, volume: float) -> None:
        room = self.room
        if room is None:
            return
        gain = room.gain_min + volume * (room.gain_max - room.gain_min)
        step = room.gain_step or 0.1
        gain = round(gain / step) * step
        await self._client.async_set_gain(self._room_id, round(gain, 2))

    async def async_volume_up(self) -> None:
        room = self.room
        if room:
            await self._client.async_set_gain(self._room_id, room.gain + VOLUME_STEP_DB)

    async def async_volume_down(self) -> None:
        room = self.room
        if room:
            await self._client.async_set_gain(self._room_id, room.gain - VOLUME_STEP_DB)

    async def async_mute_volume(self, mute: bool) -> None:
        await self._client.async_set_mute(self._room_id, mute)

    # ---------- Power (standby) ----------

    async def async_turn_on(self) -> None:
        await self._client.async_set_standby(self._room_id, False)

    async def async_turn_off(self) -> None:
        await self._client.async_set_standby(self._room_id, True)

    # ---------- Source (input) ----------

    @property
    def source(self) -> str | None:
        room = self.room
        return room.selected_input if room else None

    @property
    def source_list(self) -> list[str] | None:
        room = self.room
        return room.input_modes if room else None

    async def async_select_source(self, source: str) -> None:
        await self._client.async_set_input(self._room_id, source)

    # ---------- Sound mode (voicing profile) ----------

    @property
    def sound_mode(self) -> str | None:
        room = self.room
        if room is None or room.selected_voicing is None:
            return None
        return room.voicing_profiles.get(room.selected_voicing)

    @property
    def sound_mode_list(self) -> list[str] | None:
        room = self.room
        if room is None or not room.voicing_profiles:
            return None
        return list(room.voicing_profiles.values())

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        room = self.room
        if room is None:
            return
        for profile_id, name in room.voicing_profiles.items():
            if name == sound_mode:
                await self._client.async_select_voicing(self._room_id, profile_id)
                return

    # ---------- Now playing ----------

    @property
    def app_name(self) -> str | None:
        room = self.room
        if room and room.streaming and room.streaming.service_name:
            return room.streaming.service_name
        return None

    @property
    def media_title(self) -> str | None:
        room = self.room
        if room and room.streaming and len(room.streaming.display) > 0:
            return room.streaming.display[0] or None
        return None

    @property
    def media_artist(self) -> str | None:
        room = self.room
        if room and room.streaming and len(room.streaming.display) > 1:
            return room.streaming.display[1] or None
        return None

    @property
    def media_album_name(self) -> str | None:
        room = self.room
        if room and room.streaming and len(room.streaming.display) > 2:
            return room.streaming.display[2] or None
        return None

    @property
    def media_duration(self) -> int | None:
        room = self.room
        if room and room.streaming and room.streaming.track_length > 0:
            return int(room.streaming.track_length)
        return None

    @property
    def media_position(self) -> int | None:
        room = self.room
        if room and room.streaming and room.streaming.track_length > 0:
            return int(room.streaming.track_position)
        return None

    @property
    def media_position_updated_at(self) -> datetime | None:
        room = self.room
        if room and room.streaming:
            return room.streaming.position_updated_at
        return None

    @property
    def media_image_url(self) -> str | None:
        room = self.room
        if room and room.streaming:
            return room.streaming.album_art_url
        return None

    @property
    def media_image_remotely_accessible(self) -> bool:
        return False

    # ---------- Transport ----------

    async def _streaming_command(self, *candidates: str) -> None:
        room = self.room
        methods = room.streaming.methods if room and room.streaming else {}
        for method in candidates:
            if methods.get(method):
                await self._client.async_streaming_command(self._room_id, method)
                return

    async def async_media_play(self) -> None:
        await self._streaming_command("play", "playPause")

    async def async_media_pause(self) -> None:
        await self._streaming_command("pause", "playPause")

    async def async_media_next_track(self) -> None:
        await self._streaming_command("next")

    async def async_media_previous_track(self) -> None:
        await self._streaming_command("previous", "prev")
