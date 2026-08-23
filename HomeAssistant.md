# Home Assistant / Dutch & Dutch — Environment & Project Handoff

Context file for picking up work on the Dutch & Dutch 8c Home Assistant
integration without rediscovering everything. Last updated: 2026-08-23.

## Access / environment

- **Home Assistant host**: `rock.home` (10.0.101.20) — passwordless ssh as the
  current user works (`ssh rock.home`).
- **HA runs in docker**, container name `homeassistant`. HA 2026.7.4,
  Python 3.14 inside the container. Restart with
  `ssh rock.home docker restart homeassistant` (takes ~30–60 s).
- **HA config dir** is mounted on rock.home at `/mnt/disk/homeassistant`
  (inside the container it's `/config`). Custom integrations:
  `/mnt/disk/homeassistant/custom_components/`.
- **No HA API token is available** (nothing in secrets.yaml), so config flows
  can't be driven headlessly. To manipulate config entries programmatically:
  stop the container, edit `/mnt/disk/homeassistant/.storage/core.config_entries`
  (JSON), start the container. A backup from 2026-08-21 exists at
  `.storage/core.config_entries.bak-dutchdutch`.
- The rock.home **host has no python3**; run Python inside the container.
  `docker exec` needs `-i` when piping a script over ssh:
  `ssh rock.home 'docker exec -i homeassistant python3 -' <<'EOF' ... EOF`
- Handy check for live speaker connections: `ssh rock.home 'ss -tn | grep 8768'`
  (remember IPv6 lines — don't grep only for the IPv4 addresses).

## The speakers

- Stereo pair of Dutch & Dutch 8c, room **"Music Room"**,
  room id `f7b42050-90ba-4dc9-90a6-bb9d4224fa80`, firmware 2.4.81.
  - `8c-155` = 10.0.101.174 (fd6a:a4f6:fb1f:4a02:eaeb:11ff:fe25:3df9)
  - `8c-156` = 10.0.101.175 (fd6a:a4f6:fb1f:4a02:6264:5ff:fe29:70f5) — **network master**
- Discovered via mDNS service type `_x-clerk._tcp.local.`.
- Each speaker serves the official "D&D Control" web app at `http://<ip>/`
  (single ~2.3 MB HTML+JS bundle — grepping that bundle is how protocol
  details were reverse-engineered).

## Protocol crash course

WebSocket `ws://<speaker>:8768`, JSON envelope:
`{"meta": {"id": <uuid>, "endpoint": <str>, "method": read|write|update|subscribe|create|delete|select|notify, "targetType": "room"|"device", "target": <id>}, "data": ...}`.
Responses echo `meta.id`; errors come as `{"errors": [{"detail": ...}]}`.

- State: `network` read → `data.state.{...}.data` entries with `type: "room"`.
  Subscribe with `{"endpoint": "network", "method": "subscribe"}` → pushed
  `notify` messages with the same shape.
- Commands (targetType room, target = room id):
  `gain2` update `{gain: dB}` (limits −80..+6 step 0.1);
  `mute` update `[{mute: bool, positionID: "global"}]`;
  `sleep` update `{enable: bool}`;
  `selectedInput` update `{input: name}`;
  `selectedXLR` update `{xlr: aes|analogLowGain|analogHighGain}`;
  `linear-phase` update `{enable: bool}`;
  `tone-control` select `{voicing: profileId}`;
  `preset2` select `{id: presetId}`;
  `streaming-api` update `{method: play|pause|next|previous, arguments: []}`.
- **Gotcha #1 — the master**: writes handled by the "Network Plugin"
  (selectedInput, sleep, …) only succeed on the **master** speaker; on the
  other member they fail with `Handler Network Plugin error: Network is not
  locked`. (`gain2` works on either.) Resolve the master with
  `{"endpoint": "master", "method": "read"}` → `data.address.ipv4/ipv6`.
  The integration's client does this automatically and reconnects to the
  master ("follow the master" in `api.py`).
- **Gotcha #2 — input naming**: `inputModes` lists the XLR source as
  `"AES Streamer"` but `selectedInput` reports/accepts `"XLR"`. Normalize to
  `"XLR"` (done in `parse_room`).
- Politeness: the official app identifies itself on connect via
  `{"endpoint": "yoctopus:label", "method": "update", "data": "<client name>"}`;
  the integration sends "Home Assistant".
- Reference implementation: Rust library at `~/work/remote/hub/dutchdutch-ascend`
  (mDNS + protocol; note it does NOT handle the master gotcha).

## The integration

- Source of truth: `~/work/homeassistant-dutchdutch` (this repo), pushed to
  **https://github.com/dannyfiresnake/homeassistant-dutchdutch** (public,
  release v0.1.0 exists; hacs.json present so it works as a HACS custom repo).
- Layout: `custom_components/dutchdutch/` — `api.py` is a standalone
  (HA-import-free) asyncio client; `media_player.py` (volume/mute/standby/
  source/voicing-as-sound-mode/now-playing/transport), `select.py` (input,
  XLR mode, preset), `switch.py` (linear phase), config flow with zeroconf
  discovery. One HA device per *room* (both speakers advertise; deduped by
  room id as the config entry unique_id).
- **Deploy** (no build step):
  `rsync -a --delete ~/work/homeassistant-dutchdutch/custom_components/dutchdutch/ rock.home:/mnt/disk/homeassistant/custom_components/dutchdutch/ && ssh rock.home docker restart homeassistant`
- **Verify** after deploy: `docker logs --since 5m homeassistant 2>&1 | grep -i dutchdutch`
  (only expected line: the generic "custom integration not tested" loader
  warning), and `ss -tn | grep 8768` shows one ESTAB connection to the master.
  `api.py` can be exercised standalone inside the container
  (`sys.path.insert(0, "/config/custom_components"); from dutchdutch.api import DutchDutchClient`).
  Safe no-op write test: set gain/input to their current values.

## History / current state (as of 2026-08-23)

- 2026-08-21: integration built, deployed, configured (entry "Music Room").
  Initial version connected to 8c-155 (non-master) → input/standby writes
  failed with "Network is not locked", causing sluggish/weird behavior while
  the user switched inputs; user's web player also acted up. Fixed by
  master-follow (commit `2ec6d1d`). User still saw speaker weirdness, so the
  integration was fully disabled (component moved out + entry disabled) to
  isolate; HA was verified to hold zero speaker connections.
- 2026-08-23: integration **re-enabled** and healthy — component restored to
  `custom_components/`, entry re-enabled. On startup a zeroconf flow updated
  the entry host to the master's IPv6 (`fd6a:...:70f5`); that's fine, the
  client follows the master regardless of which pair member the host points at.
  Live connection to the master confirmed, no errors in logs.
- Entity ids: `media_player.music_room`, `select.music_room_xlr_mode`,
  `select.music_room_preset`, `switch.music_room_linear_phase`,
  `select.office_danny_music_music_room_input` (odd prefix: device had been
  renamed before that entity was created; cosmetic only).

## Disable / enable procedure (isolation testing)

Disable completely (guarantees HA opens no connections to the speakers, since
even zeroconf discovery flows connect during validation):
1. `ssh rock.home docker stop homeassistant`
2. `mv /mnt/disk/homeassistant/custom_components/dutchdutch /mnt/disk/homeassistant/disabled_components/dutchdutch`
3. Edit `.storage/core.config_entries`: set the dutchdutch entry's
   `"disabled_by": "user"` (copy file off, edit with python locally, copy back).
4. `docker start homeassistant`; verify `ss -tn | grep 8768` is empty.

Enable: reverse the steps (`disabled_by: null`, move dir back, restart).
If the speakers themselves get wedged (web player flaky, etc.), power-cycle
both speakers and let them renegotiate master for a couple of minutes.

## Known unknowns / next steps

- **Album art URL construction is unverified** (`_parse_streaming` in api.py
  guesses `http://<master-ip>:8768<path>`); nothing was streaming during
  testing. If artwork is missing while Roon/Spotify plays, fix there.
- Tone controls (sub/mid/treble numbers), nightmode, sleep timer are in the
  room state but not exposed as entities yet.
- If publishing to HA core is ever wanted: extract `api.py` to a PyPI package,
  add config-flow tests, brands + docs PRs (api.py was written HA-free on
  purpose).
