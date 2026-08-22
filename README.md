# Dutch & Dutch 8c for Home Assistant

Custom Home Assistant integration for [Dutch & Dutch](https://dutchdutch.com/)
networked speakers (8c). Talks the local Ascend WebSocket protocol on port
8768 — no cloud required.

## Features

- **Automatic discovery** via mDNS (`_x-clerk._tcp`), or add by IP address
- **Media player** entity per room:
  - Volume (mapped onto the room's gain range in dB), mute, volume step (1 dB)
  - Power (standby / wake)
  - Source selection (Spotify Connect, Roon Ready, XLR, File Player, …)
  - Sound mode selection (voicing profiles)
  - Now playing metadata, artwork, and transport controls when streaming
- **Select** entities: XLR input mode (AES / analog low/high gain), room preset
- **Switch** entity: linear phase filter
- **Push updates** — state changes made from the Dutch & Dutch app show up
  immediately via the speaker's subscription channel; automatic reconnect

## Installation

Copy `custom_components/dutchdutch` into your Home Assistant `config/custom_components/`
directory and restart Home Assistant. Discovered speakers appear under
**Settings → Devices & services**; otherwise add the integration manually and
enter a speaker's IP address.

Both speakers of a stereo pair advertise the same *room*; the integration
creates one device per room (deduplicated by room ID).

## Protocol

Based on the [dutchdutch-ascend](https://github.com/dannyfiresnake/dutchdutch-ascend)
Rust implementation: JSON request/response over WebSocket (`ws://<speaker>:8768`),
`network` read/subscribe for state, `gain2`/`mute`/`sleep`/`selectedInput`/
`selectedXLR`/`linear-phase`/`tone-control`/`preset2`/`streaming-api` endpoints
for control.

## Disclaimer

Unofficial, community-developed; not affiliated with or endorsed by Dutch & Dutch.
