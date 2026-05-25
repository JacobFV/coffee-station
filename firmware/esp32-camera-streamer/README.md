# ESP32 Camera Streamer

This firmware makes an ESP32 camera board expose a simple HTTP camera stream that
Coffee Station can auto-discover.

It intentionally does not try to make the ESP32 a USB UVC camera. UVC requires a
native-USB ESP32 variant, exact board-specific descriptors, and matching camera
pins. The HTTP stream is the simplest reliable path for ESP32-CAM hardware.

## Build

```bash
pio run -d firmware/esp32-camera-streamer
```

The default environment is `esp32s3_xiao_sense`. Other profiles:

```bash
pio run -d firmware/esp32-camera-streamer -e esp32s3_eye
pio run -d firmware/esp32-camera-streamer -e ai_thinker_esp32_cam
```

## Flash

```bash
pio run -d firmware/esp32-camera-streamer -e esp32s3_xiao_sense -t upload --upload-port /dev/ttyACM1
```

If the upload port is owned by `root:dialout`, add your user to `dialout` and
log out/in, or run a one-time privileged permission change before flashing.

## Network

The firmware always starts an access point:

- SSID: `coffee-station-cam`
- Password: `coffeecam`
- Stream: `http://192.168.4.1:81/stream`
- Snapshot: `http://192.168.4.1/capture`

To also join a normal Wi-Fi network, add build flags:

```ini
-DWIFI_SSID=\"your-ssid\"
-DWIFI_PASSWORD=\"your-password\"
```

When connected, the serial log prints the station IP, and Coffee Station can scan
`esp32cam.local` or the printed stream URL.
