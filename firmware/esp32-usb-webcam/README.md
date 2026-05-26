# ESP32-S3 USB Webcam

This firmware makes a Seeed XIAO ESP32S3 Sense enumerate as a USB Video Class
webcam. It uses Espressif's `usb_device_uvc` component and the XIAO camera
pinout.

Build:

```bash
pio run -d firmware/esp32-usb-webcam
```

Flash:

```bash
pio run -d firmware/esp32-usb-webcam -t upload --upload-port /dev/ttyACM1
```

After reset, Linux should show an `Espressif ESP UVC Device` and create
`/dev/video0`. Coffee Station can then discover it with the existing camera scan.
