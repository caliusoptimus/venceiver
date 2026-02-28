# Venstar WiFi Sensor Receiver (Home Assistant)

This integration listens for UDP packets from a real Venstar `ACC-TSENWIFI` sensor.

## What it does

1. Opens a UDP listener (default `0.0.0.0:5001`).
2. During setup, shows a pairing step with a `Pair` button and a fixed 5-minute window.
3. Captures sensor key from pairing packets (`type 43`) before entry creation.
4. Accepts only authenticated update packets (`type 42`) after pairing.
5. Suppresses duplicate packet bursts from the physical sensor.
6. Exposes received temperature and packet metadata as HA sensors.

## Entities

1. `sensor.<entry>_received_temperature` (temperature sensor)
2. `sensor.<entry>_received_temperature_c` (fixed Celsius)
3. `sensor.<entry>_last_seen`
4. `sensor.<entry>_battery` (%)
5. `sensor.<entry>_unit_id`
6. `sensor.<entry>_sensor_type` (outdoor/return/remote/supply)
7. `sensor.<entry>_sensor_name` (name from packets)
