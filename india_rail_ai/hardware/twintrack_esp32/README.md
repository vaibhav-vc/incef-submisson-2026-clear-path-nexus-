# TwinTrack tabletop node

One ESP32 per model train. Each node:
- **reports** marker passes and an optional obstacle reading to the laptop;
- **shows** the controller-approved advisory on a small OLED screen.

It has no output that could control anything.

**Status: firmware written but NOT compiled or bench-tested.** Treat the first build as a bring-up exercise, and record photos and video into `seva2026/evidence/hardware/`.

## Safety
- Use low-voltage, USB-powered tabletop electronics only.
- Never connect to, power from, or test near operational railway equipment.
- The ultrasonic sensor is for the demo only; it is not obstacle detection for real trains.

## Parts (per train)

| Part | Notes |
|---|---|
| ESP32 dev board | Any board with Wi-Fi |
| SSD1306 128×64 I2C OLED | SDA → GPIO 21, SCL → GPIO 22, 3.3 V |
| IR reflective or reed sensor | GPIO 27, active LOW; a marker tag or magnet at each layout marker |
| HC-SR04 (optional) | TRIG → GPIO 5. ECHO → GPIO 18 **through a 5 V→3.3 V divider** |

Libraries: Adafruit SSD1306 and Adafruit GFX (Arduino Library Manager), plus the ESP32 board package.

## Set up
1. On the laptop, run `python -m india_rail serve --host 0.0.0.0` and note its LAN IP.
2. In `twintrack_cab.ino`, set `WIFI_SSID`, `WIFI_PASS`, `SERVER`, `TRAIN_ID` and (if used) `FEED_TOKEN`.
3. Edit the `MARKERS_A` table so each physical marker maps to a twin position (`section`, `fromNode`, `offsetKm`). Use the same route as the approved plan.
4. Flash both nodes. The first marker report hands that train over from the simulator to the hardware: the audit log shows `HARDWARE_FEED_ACTIVE`.

## How it ties into the demo
- **Marker pass:** the node posts to `/railguard/twintrack/position`. The twin validates it and rejects unknown sections, future timestamps, replayed sequences and implausible jumps.
- **Heartbeat:** the last marker is re-sent every 5 s. Unplug the sensor and the position goes STALE after 30 s. The cab then shows DATA UNAVAILABLE and the controller gets HOLD.
- **Obstacle:** an object within 12 cm posts to `/railguard/twintrack/obstacle`. The threat is CRITICAL until a controller acknowledges it, and only a controller can clear it.
- **Display:** the node polls `/railguard/cab/{train}/compact` every second. If the link fails, the screen switches to *DATA UNAVAILABLE / Follow signals* instead of keeping old guidance.

## Known limits
- The implausible-movement check uses the twin's simulated clock. Place markers, and set the Auto speed in Nexus Control, so that the scaled km between markers is reachable in the scaled time. Otherwise reports are correctly rejected as jumps.
- After a node reboots its sequence counter restarts. Reload the scenario so the server accepts it again.
