# Venstar WiFi Sensor Receiver - User Guide

This integration receives packets from real Venstar `ACC-TSENWIFI` wireless sensors and exposes decoded values in Home Assistant.

## Related Projects

- Emulator counterpart (`venmulator`): https://github.com/caliusoptimus/venmulator

## Tested Hardware

- Sensor ACC-TSENWIFI
- Venstar WiFi Sensor Emulator

## What It Does

- Listens for Venstar sensor UDP packets on your local network (default `0.0.0.0:5001`)
- Runs pairing during setup
- Captures and stores sensor key from pairing packets (`type 43`)
- Accepts only authenticated update packets (`type 42`) after pairing
- Suppresses duplicate burst packets from physical sensors
- Supports multiple receiver entries sharing the same listen endpoint
- Routes packets per entry by paired identity (MAC/unit ID/auth), so entries remain independent

## Requirements

1. Venstar sensor that uses the `ACC-TSENWIFI` protocol.
2. Home Assistant host reachable on the same network path as sensor traffic.

## Install Without HACS

1. Copy the `custom_components` folder into your Home Assistant config directory.

## Install With HACS (Custom Repository)

1. Open HACS.
2. Go to `Integrations`.
3. Open the menu and choose `Custom repositories`.
4. Add repository URL:
   1. `https://github.com/caliusoptimus/venceiver`
   2. Category: `Integration`
5. Install `Venstar WiFi Sensor Receiver`.
6. Restart Home Assistant.

## Add and Pair a Sensor Receiver Entry

1. In Home Assistant:
   1. Go to `Settings > Devices & Services`.
   2. Add integration: `Venstar WiFi Sensor Receiver`.
   3. Fill setup fields.
2. On `Ready to pair?`, click `Pair`.
3. Put the physical sensor into pairing mode. (Sensor must first be put on the WiFi network via the Venstar app)
4. Wait for `Pairing complete`.
5. Click `Finish` to create the entry.
6. Sensor can take a while before sending the first temperature packet. Outdoor setting can take up to 5 minutes.

Pairing is completed during setup. Re-pairing is not exposed afterward.

## Setup Fields (Plain Language)

1. `Entry Name`
   1. Friendly name shown in Home Assistant.
2. `Listen IP`
   1. Local interface/address to bind listener (`0.0.0.0` listens on all IPv4 interfaces).
3. `Listen Port`
   1. UDP port for Venstar sensor packets (usually `5001`).
4. `Unit ID Filter`
   1. `Any` accepts all unit IDs for pairing candidate packets.
   2. `1` to `20` restricts matching to a specific unit ID.

## Entities

1. `sensor.<entry>_received_temperature` (fixed Fahrenheit)
2. `sensor.<entry>_received_temperature_c` (fixed Celsius)
3. `sensor.<entry>_last_seen`
4. `sensor.<entry>_battery` (%)
5. `sensor.<entry>_unit_id`
6. `sensor.<entry>_sensor_type` (`Outdoor`/`Return`/`Remote`/`Supply`)
7. `sensor.<entry>_sensor_name`

## Notes on Temperature Units

- Venstar packet temperature is native Celsius (0.5C index steps).



