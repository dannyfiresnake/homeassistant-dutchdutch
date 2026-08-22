"""Async client for Dutch & Dutch Ascend speakers.

Speaks the local WebSocket protocol on port 8768. The protocol is a JSON
request/response envelope with a ``meta`` block (uuid, endpoint, method) and
an optional ``data`` payload. Room state arrives via the ``network`` endpoint
and is pushed through a subscription as ``notify`` messages.

This module is intentionally free of Home Assistant imports so it can be
exercised standalone.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10
CONNECT_TIMEOUT = 15
RECONNECT_MIN = 5
RECONNECT_MAX = 60

# XLR sub-modes that the device mixes into inputModes alongside real sources.
XLR_MODES = ("aes", "analogLowGain", "analogHighGain")

# The device reports the XLR source as "AES Streamer" in inputModes but as
# "XLR" in selectedInput. Normalize to "XLR" everywhere (same workaround as
# the reference implementation).
_INPUT_ALIASES = {"AES Streamer": "XLR"}


class DutchDutchError(Exception):
    """Base error."""


class CannotConnect(DutchDutchError):
    """Connection to the speaker failed."""


class NotConnected(DutchDutchError):
    """No active connection."""


class ApiError(DutchDutchError):
    """The speaker returned an error response."""


@dataclass
class StreamingInfo:
    """Now-playing state for the active streaming source."""

    service_name: str
    display: list[str]
    is_playing: bool
    track_length: float  # seconds
    track_position: float  # seconds
    shuffle: bool
    repeat: str
    methods: dict[str, bool]  # streaming-api method name -> callable
    album_art_url: str | None
    position_updated_at: datetime = field(compare=False)


@dataclass
class DutchDutchRoom:
    """Parsed state of a Dutch & Dutch room."""

    room_id: str
    name: str
    gain: float
    gain_min: float
    gain_max: float
    gain_step: float
    muted: bool
    sleep: bool
    selected_input: str | None
    selected_xlr: str | None
    input_modes: list[str]
    xlr_modes: list[str]
    voicing_profiles: dict[str, str]  # id -> name
    selected_voicing: str | None
    presets: dict[str, str]  # id -> name
    selected_preset: str | None
    linear_phase: bool
    member_names: list[str]
    version: str | None
    streaming: StreamingInfo | None
    raw: dict[str, Any] = field(compare=False, repr=False)


def _parse_streaming(data: dict[str, Any], fallback_host: str) -> StreamingInfo | None:
    info = data.get("streamingInfo")
    if not isinstance(info, dict):
        return None
    service = info.get("serviceName") or ""
    if not service:
        return None

    methods = {
        name: bool(meth.get("callable"))
        for name, meth in ((info.get("api") or {}).get("methods") or {}).items()
        if isinstance(meth, dict)
    }

    art_url: str | None = None
    art = info.get("albumArt")
    if isinstance(art, dict) and art.get("url"):
        url = str(art["url"])
        if url.startswith(("http://", "https://")):
            art_url = url
        else:
            master = art.get("master") or {}
            hosts = list(master.get("ip4") or []) + list(master.get("local") or [])
            host = hosts[0] if hosts else fallback_host
            if not url.startswith("/"):
                url = f"/{url}"
            art_url = f"http://{host}:{DutchDutchClient.DEFAULT_PORT}{url}"
        # Cache-buster so HA refetches when the artwork changes.
        last_update = art.get("lastUpdate") or art.get("last_update")
        if last_update is not None and "?" not in art_url:
            art_url = f"{art_url}?t={last_update}"

    return StreamingInfo(
        service_name=str(service),
        display=[str(line) for line in (info.get("display") or [])],
        is_playing=bool(info.get("is_playing")),
        track_length=float(info.get("track_length") or 0.0) / 1000.0,
        track_position=float(info.get("track_position") or 0.0) / 1_000_000_000.0,
        shuffle=bool(info.get("shuffle")),
        repeat=str(info.get("repeat") or ""),
        methods=methods,
        album_art_url=art_url,
        position_updated_at=datetime.now(UTC),
    )


def parse_room(data: dict[str, Any], fallback_host: str) -> DutchDutchRoom | None:
    """Parse a room object from network state. Returns None if not parseable."""
    room_id = data.get("id")
    name = data.get("name")
    gain = data.get("gain") or {}
    if not room_id or not name or "global" not in gain:
        return None

    limits = gain.get("limits") or {}

    raw_modes = [str(m) for m in (data.get("inputModes") or [])]
    input_modes: list[str] = []
    xlr_modes: list[str] = []
    for mode in raw_modes:
        if mode in XLR_MODES:
            xlr_modes.append(mode)
        else:
            input_modes.append(_INPUT_ALIASES.get(mode, mode))

    selected_input = data.get("selectedInput")
    if selected_input is not None:
        selected_input = _INPUT_ALIASES.get(str(selected_input), str(selected_input))

    mute = data.get("mute") or {}

    voicing = {
        profile_id: str(profile.get("name") or profile_id)
        for profile_id, profile in (data.get("voicing") or {}).items()
        if isinstance(profile, dict)
    }
    presets = {
        preset_id: str(preset.get("name") or preset_id)
        for preset_id, preset in (data.get("presets") or {}).items()
        if isinstance(preset, dict)
    }

    member_names = sorted(
        str(name) for name in (data.get("memberNames") or {}).values()
    )

    return DutchDutchRoom(
        room_id=str(room_id),
        name=str(name),
        gain=float(gain["global"]),
        gain_min=float(limits.get("min", -80.0)),
        gain_max=float(limits.get("max", 0.0)),
        gain_step=float(limits.get("step", 0.5)),
        muted=bool(mute.get("global")),
        sleep=bool(data.get("sleep")),
        selected_input=selected_input,
        selected_xlr=data.get("selectedXLR"),
        input_modes=input_modes,
        xlr_modes=xlr_modes,
        voicing_profiles=voicing,
        selected_voicing=data.get("selectedVoicingProfile"),
        presets=presets,
        selected_preset=data.get("lastSelectedPreset"),
        linear_phase=bool(data.get("linearPhase")),
        member_names=member_names,
        version=str(data["version"]) if data.get("version") is not None else None,
        streaming=_parse_streaming(data, fallback_host),
        raw=data,
    )


class DutchDutchClient:
    """WebSocket client for a Dutch & Dutch speaker (room master or member)."""

    DEFAULT_PORT = 8768

    def __init__(
        self, host: str, port: int = DEFAULT_PORT, session: aiohttp.ClientSession | None = None
    ) -> None:
        self.host = host
        self.port = port
        self._session = session
        self._owns_session = session is None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task[None] | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._listeners: list[Callable[[], None]] = []
        self._closed = True
        self._connected = False
        self._ready: asyncio.Event = asyncio.Event()
        self.rooms: dict[str, DutchDutchRoom] = {}

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def _url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"ws://{host}:{self.port}"

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a state/availability listener. Returns an unsubscribe callable."""
        self._listeners.append(listener)

        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    def _notify(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001 - listener bugs must not kill the loop
                _LOGGER.exception("Error in Dutch & Dutch state listener")

    async def async_connect(self) -> None:
        """Connect, load initial state, and start the reconnecting listen loop."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        self._closed = False
        self._ready = asyncio.Event()
        self._task = asyncio.create_task(self._run())
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                await self._ready.wait()
        except TimeoutError:
            await self.async_disconnect()
            raise CannotConnect(f"Timeout connecting to {self._url}") from None
        if not self.rooms:
            await self.async_disconnect()
            raise CannotConnect(f"No rooms found on {self.host}")

    async def async_disconnect(self) -> None:
        """Close the connection and stop reconnecting."""
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        self._connected = False
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def _run(self) -> None:
        backoff = RECONNECT_MIN
        assert self._session is not None
        while not self._closed:
            try:
                async with asyncio.timeout(CONNECT_TIMEOUT):
                    ws = await self._session.ws_connect(self._url, heartbeat=25.0)
            except (aiohttp.ClientError, OSError, TimeoutError) as err:
                _LOGGER.debug("Connection to %s failed: %s", self._url, err)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_MAX)
                continue

            backoff = RECONNECT_MIN
            self._ws = ws
            init_task = asyncio.create_task(self._initialize())
            try:
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        self._handle_message(msg.data)
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.CLOSING,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        break
            except (aiohttp.ClientError, OSError) as err:
                _LOGGER.debug("WebSocket error on %s: %s", self._url, err)
            finally:
                init_task.cancel()
                self._ws = None
                self._abort_pending()
                if self._connected:
                    self._connected = False
                    if not self._closed:
                        _LOGGER.warning("Lost connection to Dutch & Dutch at %s", self.host)
                    self._notify()

            if not self._closed:
                await asyncio.sleep(RECONNECT_MIN)

    async def _initialize(self) -> None:
        """Fetch initial state and subscribe to updates on a fresh connection."""
        try:
            response = await self._request("network", "read")
            state = (response.get("data") or {}).get("state")
            if isinstance(state, dict):
                self._process_state(state)
            await self._send(
                {"meta": {"id": str(uuid.uuid4()), "endpoint": "network", "method": "subscribe"}}
            )
        except DutchDutchError as err:
            _LOGGER.warning("Failed to initialize connection to %s: %s", self.host, err)
            if self._ws is not None:
                await self._ws.close()
            return
        self._connected = True
        self._ready.set()
        _LOGGER.debug("Connected to Dutch & Dutch at %s, rooms: %s", self.host, list(self.rooms))
        self._notify()

    def _abort_pending(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(NotConnected("Connection closed"))
        self._pending.clear()

    def _handle_message(self, text: str) -> None:
        try:
            payload = json.loads(text)
        except ValueError:
            _LOGGER.debug("Ignoring non-JSON message from %s", self.host)
            return
        if not isinstance(payload, dict):
            return

        meta = payload.get("meta") or {}
        errors = payload.get("errors")
        fut = self._pending.pop(str(meta.get("id")), None)
        if fut is not None and not fut.done():
            if errors:
                detail = errors[0].get("detail", "unknown error") if errors else "unknown error"
                fut.set_exception(ApiError(detail))
            else:
                fut.set_result(payload)
            # A read response also carries state; fall through to process it.

        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("state"), dict):
            self._process_state(data["state"])

    def _process_state(self, state: dict[str, Any]) -> None:
        changed = False
        for entry in state.values():
            data = entry.get("data") if isinstance(entry, dict) else None
            if not isinstance(data, dict) or data.get("type") != "room":
                continue
            room = parse_room(data, self.host)
            if room is None:
                continue
            if self.rooms.get(room.room_id) != room:
                self.rooms[room.room_id] = room
                changed = True
        if changed:
            self._notify()

    async def _send(self, message: dict[str, Any]) -> None:
        ws = self._ws
        if ws is None or ws.closed:
            raise NotConnected(f"Not connected to {self.host}")
        await ws.send_str(json.dumps(message))

    async def _request(
        self,
        endpoint: str,
        method: str,
        data: Any = None,
        room_id: str | None = None,
    ) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        message: dict[str, Any] = {
            "meta": {"id": request_id, "endpoint": endpoint, "method": method}
        }
        if room_id is not None:
            message["meta"]["targetType"] = "room"
            message["meta"]["target"] = room_id
        if data is not None:
            message["data"] = data

        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = fut
        try:
            await self._send(message)
            async with asyncio.timeout(REQUEST_TIMEOUT):
                return await fut
        except TimeoutError as err:
            raise DutchDutchError(f"Request {endpoint}/{method} timed out") from err
        finally:
            self._pending.pop(request_id, None)

    def _update_room(self, room_id: str, **changes: Any) -> None:
        """Optimistically apply changes to local state and notify listeners."""
        room = self.rooms.get(room_id)
        if room is None:
            return
        self.rooms[room_id] = replace(room, **changes)
        self._notify()

    # ---------- Commands ----------

    async def async_set_gain(self, room_id: str, gain: float) -> None:
        """Set the room volume in dB."""
        room = self.rooms.get(room_id)
        if room is not None:
            gain = max(room.gain_min, min(room.gain_max, gain))
        await self._request("gain2", "update", {"gain": gain}, room_id)
        self._update_room(room_id, gain=gain)

    async def async_set_mute(self, room_id: str, mute: bool) -> None:
        await self._request(
            "mute", "update", [{"mute": mute, "positionID": "global"}], room_id
        )
        self._update_room(room_id, muted=mute)

    async def async_set_standby(self, room_id: str, standby: bool) -> None:
        await self._request("sleep", "update", {"enable": standby}, room_id)
        self._update_room(room_id, sleep=standby)

    async def async_set_input(self, room_id: str, input_name: str) -> None:
        await self._request("selectedInput", "update", {"input": input_name}, room_id)
        self._update_room(room_id, selected_input=input_name)

    async def async_set_xlr_mode(self, room_id: str, mode: str) -> None:
        await self._request("selectedXLR", "update", {"xlr": mode}, room_id)
        self._update_room(room_id, selected_xlr=mode)

    async def async_set_linear_phase(self, room_id: str, enabled: bool) -> None:
        await self._request("linear-phase", "update", {"enable": enabled}, room_id)
        self._update_room(room_id, linear_phase=enabled)

    async def async_select_voicing(self, room_id: str, profile_id: str) -> None:
        await self._request("tone-control", "select", {"voicing": profile_id}, room_id)
        self._update_room(room_id, selected_voicing=profile_id)

    async def async_select_preset(self, room_id: str, preset_id: str) -> None:
        await self._request("preset2", "select", {"id": preset_id}, room_id)
        self._update_room(room_id, selected_preset=preset_id)

    async def async_streaming_command(
        self, room_id: str, method: str, arguments: list[Any] | None = None
    ) -> None:
        await self._request(
            "streaming-api",
            "update",
            {"method": method, "arguments": arguments or []},
            room_id,
        )
