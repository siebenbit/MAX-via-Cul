# MAX! via CUL

[English](README.en.md) | [Deutsch](README.md)

A Home Assistant custom integration for eQ-3 MAX! devices connected to a CUL
or CUNO running CULFW. For installation through HACS or manual installation,
see the [repository README](../../README.md).

The integration communicates directly with the CUL over TCP. It provides
both temperature control and direct associations between MAX! devices.
Window contacts, wall thermostats and radiator thermostats can therefore
continue cooperating while Home Assistant is offline. External sensors mapped
through Home Assistant to virtual contacts still require Home Assistant.

## Features

- Pair MAX! devices directly from Home Assistant.
- Control radiator and wall thermostats.
- Edit weekly schedules using a draft, save and discard workflow.
- Write group IDs and link partners directly to devices.
- Create virtual MAX! window contacts for external sensors, including Zigbee,
  Matter and IKEA devices.
- Monitor last contact, stale states, acknowledgements, retries and pending
  configuration.
- Export and import the known MAX! topology as JSON.

## Architecture

The integration uses CULFW's MAX!/MORITZ mode over TCP. It is designed for
local operation with existing MAX! hardware, useful diagnostics and room
control performed by the devices themselves.

Its main components are:

- A serial command queue for write operations.
- Acknowledgement-based retries for configuration and control commands.
- Pending configuration delivery for sleeping window contacts, following
  patterns from FHEM and Homegear.
- Persistent storage of known devices and their topology.
- Direct device associations.
- No routine wake-up polling, to limit battery consumption and radio traffic.

## Supported Devices

- MAX! radiator thermostats
- MAX! radiator thermostat+
- MAX! wall thermostats
- MAX! window contacts (shutter contacts)
- Virtual MAX! window contacts created by this integration

## Setup

You need a CUL/CUNO running CULFW with MAX!/MORITZ support, TCP access
(typically port `2323`) and the `cul_max` custom integration installed in
Home Assistant.

The configuration flow asks for the CUL host name or IP address, TCP port and
the integration's own MAX! radio address. The default address is `123456`.

When replacing an existing MAX! setup, consider reusing the old Cube's radio
identity or resetting and pairing the devices again. Devices remember their
paired controller. Do not run two controllers with the same radio identity
at the same time.

## Reset and Pairing

Before pairing any device:

1. Call `cul_max.start_pairing` in Home Assistant.
2. Put the device into pairing mode.

These procedures are a practical reference for common MAX! models. Wall
thermostat behaviour can vary by firmware version.

### Radiator thermostat

To reset:

1. Remove the battery.
2. Hold all three buttons simultaneously.
3. Reinsert the battery while holding the buttons.
4. Wait until `res` appears on the display.

To pair:

1. Start pairing in Home Assistant.
2. Hold the thermostat's Boost button for approximately three seconds.
3. The display counts down from `30` to `0`.
4. The thermostat should pair during this countdown.

### Window contact

To reset:

1. Remove the battery.
2. Hold the button.
3. Reinsert the battery while holding the button.
4. Keep holding it while the LED lights continuously.
5. Release the button when the LED starts blinking.

To pair:

1. Start pairing in Home Assistant.
2. Hold the contact's button for approximately three seconds.
3. The LED starts blinking and the contact should pair.

### Wall thermostat

To reset:

1. Remove both batteries and wait for a while.
2. Hold the Moon, Boost/OK and Minus buttons simultaneously.
3. Reinsert the batteries while holding the buttons.
4. A version number briefly appears, followed by `res`.

Some devices require several attempts. On some firmware versions, holding
`Mode/Menu` opens a menu where you can select `res` directly.

To pair:

1. Start pairing in Home Assistant.
2. Put the wall thermostat into pairing mode.
3. After a reset, you may need to set its time once.
4. Following successful pairing, the integration normally sends the time
   and other basic configuration automatically.

## Entities

### Thermostats

Radiator and wall thermostats expose:

- A `climate` entity for target temperature and HVAC mode.
- `text` entities for weekly schedules.
- `number` entities for comfort, eco and window-open temperatures,
  window-open duration and measurement offset.
- `Save Configuration` and `Discard Draft` buttons.
- An optional custom Lovelace card for weekly schedules.

Temperature changes preserve the current MAX! mode where possible. Changing
the target temperature in `auto` mode does not immediately force the device
into `manual` mode. The climate attributes `mode_detail` and
`mode_is_temporary` help distinguish normal weekly operation from temporary
overrides.

Changes to the schedule and configuration entities are stored as drafts.
Press **Save Configuration** to send them to the device, or **Discard Draft**
to abandon the edits. Direct service calls provide another way to configure
devices.

### Window contacts

Physical and virtual MAX! contacts expose a `binary_sensor` for their
open/closed state.

### Diagnostics

Depending on device type, diagnostic entities include:

- `Last Seen`, `Last Ack` and `Last Command Success`
- `Last Time Sync`
- `Expected Week Profile Temperature` and `Week Profile Validation`
- `Retry Count` and communication status
- `Stale`, indicating that a device has not been heard from for too long
- `Config Pending`, indicating undelivered configuration
- `Pairing State`

An integration-wide `Pairing Mode` binary sensor indicates whether the pairing
window is open. Its attributes include `pairing_until` and `remaining_seconds`.
The exact entity ID may vary; search for the integration's `Pairing Mode`
entity in Home Assistant.

Critical states also appear in device model labels, for example
`MAX! ShutterContact · discovered` or
`MAX! HeatingThermostat · pending config`.

Diagnostic attributes include:

| Area | Attributes |
| --- | --- |
| Associations | `group_id`, `linked_partners`, `peer_names`, `peer_labels`, `supported_partner_types` |
| Pairing | `is_paired`, `pairing_state` |
| Configuration | `pending_config`, `config_pending`, `last_command` |
| Time | `last_time_sync_at`, `last_reported_time` |
| Schedule | `expected_week_profile_temperature`, `week_profile_validation`, `week_profile_validation_reason`, `actual_target_temperature`, `temperature_delta_to_expected` |
| Window state | `window_open_active`, `open_window_partners`, `open_window_partner_names` |
| Pending queue | `pending_queue_type`, `pending_queue_length`, `pending_queue_current`, `pending_queue_attempts`, `pending_queue_last_error`, `pending_queue_next_attempt_at` |

Queue metadata shows the current step, retry attempts and next scheduled
attempt. Climate configuration queues continue processing in the background
when the initial attempt did not complete.

### Weekly schedule validation

`Week Profile Validation` is a best-effort diagnostic, not a readback of the
schedule stored on the device. It compares the known schedule with the current
target temperature, mode, window state and pending configuration.

| State | Meaning |
| --- | --- |
| `likely_applied` | The target temperature matches the expected schedule. |
| `pending` | Schedule or other climate configuration has not finished delivery. |
| `window_open` | An associated window contact is open. |
| `manual_override`, `temporary_override`, `boost` | The device is currently operating outside its normal weekly schedule. |
| `mismatch` | The expected and actual target temperatures differ. |
| `unknown` | There is not enough information to assess the schedule. |

Pairing states have these meanings:

- `paired`: Paired through this integration's pairing process.
- `discovered`: Seen over radio but not yet paired through this integration;
  common after migration from a Cube or another controller.
- `virtual`: A virtual device created by the integration.

## Services

Services are available in Home Assistant. See [services.yaml](services.yaml)
for their complete field definitions. Many operational services return a
response directly in Developer Tools, including topology import, room
association, time synchronisation and cleanup dry runs.

| Purpose | Services in the `cul_max` domain |
| --- | --- |
| Pairing and naming | `start_pairing`, `set_device_name` |
| Temperature and schedules | `set_temperature_config`, `set_desired_temperature`, `set_week_profile`, `set_week_profile_days` |
| Time and wake-up | `sync_time`, `wake_thermostats` |
| Device associations | `set_group_id`, `remove_group_id`, `add_link_partner`, `remove_link_partner`, `associate_devices`, `deassociate_devices` |
| Virtual contacts | `create_virtual_shutter_contact`, `delete_virtual_device`, `send_virtual_shutter_contact_state` |
| Rooms | `create_room_association`, `delete_room_association`, `rebuild_room_association` |
| Backup and cleanup | `export_topology`, `import_topology`, `cleanup_superseded_devices` |

For everyday room setup, use the room services. The lower-level group and
link services are useful for migration, repairs and debugging.

`set_desired_temperature` supports explicit MAX! modes such as `auto`,
`manual`, `boost` and temporary settings ending at an `until` time. This is
useful when investigating the difference between a weekly schedule and a
temporary override.

`wake_thermostats` is intended for occasional manual use. Frequent wake-up
commands increase battery consumption and radio traffic.

## Examples

Replace example entity IDs and device names with those from your installation.

### Start pairing from a phone

Create a script:

```yaml
script:
  cul_max_pairing_60s:
    alias: MAX Pairing 60s
    sequence:
      - action: cul_max.start_pairing
        data:
          duration: 60
```

Call pairing directly from a dashboard button:

```yaml
type: button
name: MAX Pairing
icon: mdi:link-variant-plus
tap_action:
  action: perform-action
  perform_action: cul_max.start_pairing
  data:
    duration: 60
```

Alternatively, set `perform_action` to `script.cul_max_pairing_60s` and omit
the button's `data` field.

A longer pairing window, such as 90 or 120 seconds, can be convenient when
walking to a device. The window applies to the entire integration. Avoid
leaving it open unnecessarily.

To show its status:

```yaml
type: tile
entity: binary_sensor.max_via_cul_pairing_mode
name: MAX Pairing
```

### Check and synchronise device clocks

Weekly schedules run on the devices. An incorrect device clock can make a
correct schedule appear shifted. Check `Last Time Sync` and
`last_reported_time` before changing the schedule.

Synchronise one thermostat:

```yaml
action: cul_max.sync_time
data:
  entity_id: climate.bedroom_thermostat
```

Synchronise all paired radiator and wall thermostats:

```yaml
action: cul_max.sync_time
data: {}
```

The integration already attempts time synchronisation after pairing. It also
assigns climate devices to 12 hourly time slots for periodic background clock
updates. An explicit sync is still useful after migration or when schedule
behaviour looks wrong.

### Configure comfort, eco and window-open settings

These are actual device configuration values, also known in FHEM and
Homegear as `comfortTemperature`, `ecoTemperature`, `windowOpenTemperature`
and `windowOpenDuration`.

```yaml
action: cul_max.set_temperature_config
data:
  entity_id: climate.bathroom_thermostat
  comfort_temperature: 21.0
  eco_temperature: 17.0
  window_open_temperature: 12.0
  window_open_duration: 15
```

### Set a weekly schedule

Each line contains a day followed by alternating temperatures and end times.
The final temperature applies until midnight:

```yaml
action: cul_max.set_week_profile
data:
  entity_id: climate.bathroom_thermostat
  profile: "Mon 18,07:05,23,15:30,18"
```

This means 18 °C until 07:05, 23 °C until 15:30 and 18 °C until midnight.
Times must use five-minute steps and increase strictly. Each day supports
up to 13 temperature segments. Empty fields, duplicate days and intermediate
`24:00` transitions are rejected; midnight is implied by the final temperature.

Weekly schedules require multiple radio packets per day and can take longer
to deliver than individual temperature commands. `Config Pending` may remain
active while delivery proceeds. Radio traffic and transmission limits can
increase the time needed.

In a room with a wall thermostat, normally write the schedule to the wall
thermostat. MAX! distributes control to the associated radiator thermostats;
you generally do not need to write the same schedule to each radiator.

### Weekly schedule Lovelace card

In Lovelace storage mode, the integration registers its card resource
automatically and makes it available in the visual card editor.

```yaml
type: custom:cul-max-week-profile-card
entity: climate.bathroom_thermostat
title: Bathroom weekly schedule
```

Existing manual `/local/cul-max-week-profile-card.js` resource entries are
migrated to the embedded path in storage mode. In YAML mode, register
`/cul-max/cul-max-week-profile-card.js` manually as a `module` resource.
Reload the browser after initial registration or an update if necessary.

The card displays daily schedules and opens the climate entity's more-info
dialog when clicked.

### Set up a complete room

```yaml
action: cul_max.create_room_association
data:
  room_name: Kitchen
  climate_device_names:
    - Kitchen wall thermostat
    - Kitchen left radiator
    - Kitchen right radiator
  create_virtual_shutter_contact: true
  virtual_shutter_contact_name: Kitchen virtual window contact
  bidirectional: true
```

Room associations can take time to become fully effective, especially with
several contacts and thermostats. If you previously configured a specific
`group_id` manually, pass it explicitly when creating the room; otherwise a
different free group ID may be selected.

Open and close physical window contacts a few times to help deliver pending
configuration to sleeping devices. Check `Config Pending` and peer diagnostics.
Finish by testing window opening, closing and temperature changes on the
actual devices.

### Map an external sensor to a virtual MAX! contact

1. Create a virtual contact or choose an existing one.
2. Associate it with the target room.
3. Use an automation to forward the external sensor's state.

Associate an existing virtual contact at address `A00000`:

```yaml
action: cul_max.create_room_association
data:
  room_name: Office
  climate_entity_ids:
    - climate.office_thermostat
  window_addresses:
    - A00000
  bidirectional: true
```

Forward state changes:

```yaml
alias: Office external window contact to MAX
mode: single
trigger:
  - platform: state
    entity_id: binary_sensor.office_window
condition:
  - condition: template
    value_template: "{{ trigger.to_state is not none and trigger.to_state.state in ['on', 'off'] }}"
action:
  - action: cul_max.send_virtual_shutter_contact_state
    data:
      address: A00000
      is_open: "{{ trigger.to_state.state == 'on' }}"
```

Check that the contact's pairing state is `virtual`, that the thermostat and
contact list each other as peers, and that the thermostat reacts when the
external sensor opens and closes. Virtual contact transmissions receive
priority so they do not wait behind lengthy schedule configuration queues.

Common pitfalls:

- Use `create_virtual_shutter_contact: true` only when creating a new contact;
  an existing address causes an error.
- Add existing contacts through `window_addresses`, `window_entity_ids` or
  `window_device_names`.
- `virtual_shutter_contact_address` only applies together with
  `create_virtual_shutter_contact: true`.
- Writes to physical thermostats marked `discovered` rather than `paired`
  are blocked until pairing is completed.
- For problems, check peers, pairing state, pending configuration and
  communication diagnostics on all involved devices.

### Back up and restore the topology

Export:

```yaml
action: cul_max.export_topology
data:
  path: backups/cul_max_topology.json
```

Import:

```yaml
action: cul_max.import_topology
data:
  path: backups/cul_max_topology.json
  create_virtual_devices: true
  update_names: true
  apply_group_ids: true
  apply_links: true
  apply_week_profiles: true
```

### Clean up after migration

After migration, devices may initially appear as `discovered`, and old device
or entity registry entries may remain.

1. Reset and pair affected devices if necessary.
2. Check that their pairing state is `paired`.
3. Preview cleanup candidates before removing old entries.

Preview:

```yaml
action: cul_max.cleanup_superseded_devices
data:
  dry_run: true
```

The response lists candidates directly, without requiring more verbose global
logging.

Remove superseded devices and their registry entries:

```yaml
action: cul_max.cleanup_superseded_devices
data:
  dry_run: false
  remove_registry_entries: true
```

To also remove old devices that are only marked `discovered`, add
`remove_discovered_devices: true`. This expands the cleanup beyond superseded
devices, so review the candidates with that option in a dry run first.

## Export Format and Restore Behaviour

The JSON export includes known devices, addresses, types, display names,
group IDs, link partners, weekly schedules as hex and readable daily lines,
virtual contacts and the last known device state.

Import updates existing devices and can create missing virtual contacts. It
can restore groups, links and schedules, but does not automatically create
unknown physical devices or remove additional existing links. It restores the
known topology rather than performing an exact replacement of all state.

## Reliable Operation

- Sleeping devices may need to wake before configuration can be delivered.
- Window contacts can apply changes later; monitor `Config Pending`.
- Allow time for weekly schedules and room associations to complete.
- Test physical window contacts and temperature changes after major room changes.
- Do not operate two controllers with the same radio identity simultaneously.
- Let the serial command queue handle batches of writes.
- Monitor `Last Seen`, `Stale` and communication diagnostics.

MAX! radio messages can be missed or acknowledged late. Initial setup,
pairing and bulk configuration may therefore take longer than expected.
Hardware tests depend on the specific CULFW firmware and device behaviour.

## Tests

Protocol regression tests are in [tests/test_protocol.py](tests/test_protocol.py).
Run them from the repository root:

```sh
python3 -m unittest discover -s custom_components/cul_max/tests -v
```

Coverage includes FHEM-compatible weekly schedule encoding, packet splitting,
byte-level temperature, wake-up and contact commands, parser validation,
formatting round trips, exact schedule boundaries and local time zones that
differ from the host's time zone.

## License and Acknowledgements

See [LICENSE](LICENSE) for the project's GNU General Public License, version 3.

This integration builds on the extensive protocol knowledge and practical
experience of FHEM and Homegear. Special thanks to the FHEM `10_MAX.pm` and
`14_CUL_MAX.pm` modules for message construction, schedules, time handling
and association logic, and to Homegear for its peer, queue and pending
configuration model.

The reference files include these author and copyright notices:

- FHEM `10_MAX.pm` and `14_CUL_MAX.pm`: Matthias Gehre and Wzut; GNU General
  Public License, version 2 or later.
- Homegear `MAXCentral.cpp` and `MAXPeer.cpp`: Copyright 2013–2019 Homegear
  GmbH; GNU General Public License, version 3 or later, with a documented
  OpenSSL linking exception.

## Documentation Link in Home Assistant

Home Assistant uses the `documentation` field in [manifest.json](manifest.json)
to link to this integration's documentation. It currently points to the
[English repository README](https://github.com/thnow/MAX-via-Cul/blob/main/README.md).

## Radio budget

The integration queries the actual controller credits with bare `X` on TCP
connection and before every RF transmission. CULFW32 0.2.12 uses the same format
as the inspected CULFW/a-culfw reference: two hexadecimal `TX_REPORT` characters
followed by a five-column decimal credit field, for example `00  450`. The single
TCP receive loop routes credit responses independently of MAX! frames and ACKs.
Bare `X` does not change the RF mode.

Firmware cost is `100 + (packet_bytes * 8) // 10` for `Zs`; `Zf` omits the 100-credit
preamble cost. The length byte is included. Admission requires one additional
credit as reserve. Existing wake-up behavior and packet prefixes are preserved.
The firmware maximum of 900 and boot value of 450 are never assumed available
on TCP reconnect. One credit represents 10 ms, regenerated at one credit per second.

Insufficient credits leave the packet pending. The next query is scheduled after
the deficit plus one second; estimated regeneration never authorizes transmission.
There is no periodic idle polling. A further `X` after each RF frame acts as a
firmware-processing barrier before the next frame: `LOVF` has no packet ID, so
this ordering permits attribution to the current raw write. These TCP queries
consume no RF credits. The barrier confirms firmware processing, not device reception.

PairPong and virtual window contacts retain priority. Priority packets precede
normal RF writes that have not started; each priority level uses FIFO order.
An active RF transaction is not interrupted. Priority requires the same credits
and reserve, so pairing with exhausted credits may require another attempt on
the device. Receive-triggered replies wait outside the TCP reader. Device ACK
matching is separate, and ACK deadlines start at the actual RF command write.

Missing or malformed credit responses pause transmission. Queries time out after
three seconds and close the TCP connection, preventing late responses from being
assigned to later queries. Pending packets remain queued. Query failures and
repeated `LOVF` use backoff of 5, 10, 20, 40 and at most 60 seconds. Budget waits
do not consume device ACK retries. If a connection fails after writing a frame
without a device ACK, delivery remains uncertain and a later repeat is possible.

The controller's **CUL Credits** diagnostic sensor retains the last measured
value; `budget_valid` identifies whether it is currently valid. Attributes include
`next_packet_cost`, `required_credits`, `waiting_for_budget`, `retry_in_seconds`,
`next_attempt_at`, `last_budget_query_at`, `last_budget_error` and `waiting_packets`.
Historical readings after disconnection never grant permission to transmit.
Times estimate the next check rather than guaranteeing transmission.

Sources: [CULFW32 0.2.12 X query](https://github.com/tostmann/culfw32/blob/1ce78f17a6a06b1aecf4bf53479b0f7165a25c8d/firmware/components/frontend_culfw/src/frontend_culfw.cpp#L1266-L1285),
[MAX! cost calculation](https://github.com/tostmann/culfw32/blob/1ce78f17a6a06b1aecf4bf53479b0f7165a25c8d/firmware/components/rf_proto_moritz/src/moritz_rf.cpp#L298-L307),
[FHEM credit10ms](https://github.com/mhop/fhem-mirror/blob/master/fhem/FHEM/00_CUL.pm)
and [FHEM MAX! queue](https://github.com/mhop/fhem-mirror/blob/master/fhem/FHEM/14_CUL_MAX.pm).
Firmware returning an incompatible credit format cannot authorize RF writes.

## Inspecting and controlling the transmission queue

Version 0.1.2 adds the bundled `custom:cul-max-queue-card`. Storage-mode Lovelace
resources are registered automatically. Add a manual card:

```yaml
type: custom:cul-max-queue-card
title: MAX! Queue
```

For YAML resource management, register `/cul-max/cul-max-queue-card.js?v=0.1.3`
as a `module` resource. Update the version query after subsequent releases.
The visual editor supports title, controller, device address, status and scope.
Optional fields: `config_entry_id`, `address`, `status`, `scope` (`general` or
`configuration`). One controller is selected automatically; multiple controllers
require an explicit selection. Revision changes on the queue diagnostic sensor
trigger refreshes, with a full reload after frontend reconnection. Lists are not
polled periodically and raw RF packets are not exposed.

Unsent SetTemperature commands for the same device use latest-value-wins,
including automatic, manual, boost and vacation mode with its end time. Each
replacement is a complete new intent and moves to the end of the remaining
commands. Different devices and command types remain independent. A command
waiting for credits can still be replaced or deleted. Pairing, groups, partners,
protocol responses and configuration sequences are not automatically merged.

Cancellation is checked under the TCP write lock immediately before
`writer.write()`. Once handoff starts, the command remains protected through
ACK handling, retries and reconnection. Credits are never refunded after a
handoff. Following a TCP failure without a device ACK, delivery remains uncertain
and existing retries may transmit the same frame again.

The card supports individual and selected deletion, confirmed clearing, details
and separately confirmed configuration cancellation. Clearing affects only
cancellable general commands for the selected controller and device filter,
regardless of the displayed status filter. Internal configuration packets cannot
be deleted individually. A cancelled configuration job finishes its already
transmitted step, including ACK/retries, then stops. Cancellation is saved before
success is returned, preventing restart from resuming it. Confirmed steps stay
recorded. Existing shutter-contact operations that assume delivery without an
ACK are counted separately from confirmed steps. Partial device configuration is
not rolled back; resend a complete weekly profile when required.

Actions available in the developer tools:

| Action | Parameters and result |
| --- | --- |
| `cul_max.get_queue` | Optional `config_entry_id`, `address`, `statuses`, `command_types`, `scope`; returns controller snapshots, entries, jobs and bounded history |
| `cul_max.delete_queue_entry` | `entry_id`, or `entry_ids` for batch deletion; batches report `removed` and `protected` |
| `cul_max.clear_queue` | Optional `address`; `config_entry_id` required when multiple controllers are loaded |
| `cul_max.cancel_config_job` | `job_id`, `confirm: true`, and controller selection if needed; cancels the complete persistent job |

The read action requires response data; mutation actions support optional response
data. Deleting a single protected or no-longer-present entry raises a clear
validation error. Temperature and virtual-window actions return `status`.
`cancelled` and `superseded` finish callers without indicating device success or
communication failure. Superseded climate calls do not write obsolete target
values back into HA. Device ACK matching and retry behavior remain intact.
Replaceable commands receive their final message counter only on first handoff;
retries retain it. MAX!'s eight-bit counter format is unchanged.

Statuses are `queued`, `waiting_for_credits`, `sending`, `awaiting_ack`, `retrying`,
`completed`, `failed`, `cancelled` and `superseded`. Configuration jobs additionally
use `cancelling`. The controller's queue sensor exposes waiting/active counts,
configuration jobs, the current command, replacement/cancellation counters, the
last queue error and a revision signal. Updates are coalesced over 100 ms.

General commands and their last 50 terminal records are runtime-only. A controller
admits at most 256 live general/internal RF requests; capacity errors reject new
requests without silently discarding existing ones. Persistent jobs use additive
storage schema 3 migration and retain at most 50 terminal job records.

Validation without hardware:

```sh
python3 -m unittest discover -s custom_components/cul_max/tests
node custom_components/cul_max/tests/frontend/queue-card.test.mjs
node --check custom_components/cul_max/frontend/cul-max-queue-card.js
git diff --check
```

Optional browser checks use separately installed Playwright/Chromium:
`python3 custom_components/cul_max/tests/frontend/check_queue_card.py`. They run
against a local simulated HA page, not a real HA instance or radio. Playwright is
not an integration runtime dependency. Real HA and hardware validation remain
separate from these simulation tests.

### Two-second debounce with immediate target display

Version 0.1.3 applies a **2.0-second trailing-edge debounce per thermostat** before
SetTemperature requests enter the executable queue. Each new request restarts
that device's deadline. Temperature, automatic/manual/boost/vacation mode and
vacation end time form a complete intent. Other devices and time-critical
protocol traffic are unaffected. Scheduling may execute later than the deadline,
but never admits a request before two seconds of inactivity.

The climate entity immediately displays the accepted desired value so repeated
plus/minus clicks build on the new target. Reported device state remains separate.
Old reports and completed predecessor requests cannot overwrite a newer pending
intent. After the device ACK, the next thermostat report becomes authoritative.
Automatic mode without a temperature never displays a 0 °C target. Failure or
manual cancellation restores the most recently reported target.

Climate attributes distinguish `requested_target_temperature`,
`reported_target_temperature` and `temperature_command_status`.

The queue card shows a `debouncing` preview and a local countdown. It has no
executable RF command, message counter, credit reservation or budget queries.
The preview retains its ID when admitted. Delete, batch delete and clear remove
the preview and its timer, preventing later reappearance. Existing latest-value-
wins handling remains active after admission; already transmitted requests retain
their ACK/retry handling.

Existing configuration settling is an execution prerequisite: the request enters
the queue after two seconds, but may wait for the configuration task or until ten
seconds after acceptance. The worker can continue processing configuration
packets instead of blocking on that prerequisite.

Reload/shutdown cancels timers, completes pending callers as `cancelled`, and
never restores debounce previews after restart. Timer expiry alone never means
successful transmission. Disconnecting a caller does not retract an accepted
intent; replacement, explicit cancellation or integration shutdown does.

For manually managed Lovelace resources, the current cache query is
`/cul-max/cul-max-queue-card.js?v=0.1.3`.
