# Coffee Station Testing Log

## 2026-05-23 Realtime Camera And Hardware Validation

- Started with a clean `main` tracking `origin/main`.
- No Coffee Station or Uvicorn process was running when validation began.
- Goal for this pass: make the displayed camera feed realtime when possible, then validate the agent/tool loop with the connected driver and servos using safe low-amplitude commands.
- Implemented MJPEG streaming endpoint `/api/cameras/{camera_id}/stream` and switched the desktop camera panel from 2 FPS still-image polling to a continuous stream capped by `CAMERA_FPS`.
- `pytest -q` after streaming implementation: `11 passed`.
- Started server mode on `127.0.0.1:8768`; `/api/cameras` returned camera `0` open with `1280x720` latest frames.
- `/api/cameras/0/stream?fps=30` returned `200` with `multipart/x-mixed-replace; boundary=frame` and JPEG multipart bytes, confirming the realtime display path is live.
- Installed `lerobot==0.5.1` through the project optional dependency path.
- macOS USB inspection returned `SPUSBDataType: []`.
- `pyserial` reported only `/dev/cu.debug-console`, `/dev/cu.wlan-debug`, and `/dev/cu.Bluetooth-Incoming-Port`; no `/dev/cu.usb*`, `/dev/tty.usb*`, CH340, CP210x, STM, Arduino, or LeRobot controller port is visible.
- Because no USB serial robot controller is enumerated, the physical LeRobot backend cannot be opened safely or truthfully tested yet. The code path is installed and importable, but there is no hardware device path to pass as `LEROBOT_PORT`.
- Found a compatibility issue in LeRobot `0.5.1`: `SOFollowerConfig` does not accept `id` as a constructor argument while base robot initialization expects `config.id`. Hardened the adapter by setting compatible config attributes after construction when absent.
- Restarted server mode on `127.0.0.1:8768` after changes.
- Verified manual tool dispatch:
  - `get_robot_state` returned backend `sim`.
  - `list_agent_skills` returned 3 packaged skills.
- Verified Gemini agent loop with the real `.env` API key by injecting: "Do not move the robot. Verify your tool loop by calling get_robot_state only..."
  - `/api/agent/step/{session_id}` returned `200`.
  - Gemini called `get_robot_state`.
  - Final agent message summarized backend/camera state.
  - No movement tool was called in this agent test.
- Added first-class hardware diagnostics at `/api/hardware/diagnostics` and tool `diagnose_hardware` so future agents/operators can see serial-port and USB enumeration from inside the app.
- Restarted server on `127.0.0.1:8768` with diagnostics code:
  - `/api/hardware/diagnostics` returned `ready_for_lerobot=False`, 3 serial ports, 0 USB serial ports.
  - Tool `diagnose_hardware` returned the same result.
- During desktop startup, observed the UI stream opened with `fps=1` because display FPS was incorrectly tied to agent auto-feed frequency. Fixed by adding a separate Display Hz control defaulting to `30`; Agent Hz still controls how often frames are inserted into the Gemini loop.
- Restarted the desktop app after the Display Hz fix. Startup log confirmed `/api/cameras/0/stream?fps=30` returned `200`.
- After plugging in the arm, serial enumeration found `/dev/cu.usbmodem5B415328371` with `USB VID:PID=1A86:55D3 SER=5B41532837`.
- Attempted a programmatic LeRobot connection with `Settings(robot_backend='lerobot', lerobot_port=...)`; it incorrectly stayed in sim mode. Root cause: `Settings` used env aliases without `populate_by_name=True`, so field-name constructor overrides were ignored. Fixed before hardware commands.
- After fixing settings, real LeRobot construction reached the Feetech bus and failed with `ModuleNotFoundError: No module named 'scservo_sdk'`. The plain `lerobot` optional dependency was insufficient for SO follower hardware; official docs require the Feetech extra. Updated the project optional dependency to `lerobot[feetech]>=0.4.1`.
- Installed `lerobot[feetech]`; this installed `feetech-servo-sdk==1.0.0` and provided `scservo_sdk`.
- Retried real connect on `/dev/cu.usbmodem5B415328371`; LeRobot opened the port but failed handshake because all expected servo IDs were missing:
  - expected IDs: 1, 2, 3, 4, 5, 6
  - found motors: `{}`
- Ran `FeetechMotorsBus.scan_port('/dev/cu.usbmodem5B415328371')`; it scanned baud rates and returned `{}`. This confirms the USB adapter is present but no Feetech servos are responding on the bus.
- Added `UnavailableRobot` so desktop startup with `ROBOT_BACKEND=lerobot` reports a disconnected/error backend instead of crashing when the bus is missing motors.
- Added `/api/hardware/feetech-scan` and tool `scan_feetech_motors` for repeatable low-level bus scans.
- Launched the app with `ROBOT_BACKEND=lerobot LEROBOT_PORT=/dev/cu.usbmodem5B415328371`; startup succeeded in unavailable mode and `/api/sessions/{id}` reported backend `lerobot`, `connected=False`, `unavailable=True`, with the exact missing motor ID error.
- `/api/hardware/diagnostics` reported the configured port visible: 4 serial ports total, 1 USB serial port.
- `/api/hardware/feetech-scan?port=/dev/cu.usbmodem5B415328371` returned `found: {}`.
- Also scanned `/dev/tty.usbmodem5B415328371`; it returned `found: {}`.
- Physical servo movement was not attempted because no servo IDs responded. Sending movement commands with zero detected motors would not be a valid hardware test and could hide the real bus/power/ID issue.

## 2026-05-23 Replug Retry

- User unplugged and replugged the arm/controller stack.
- Serial enumeration still shows `/dev/cu.usbmodem5B415328371` / `/dev/tty.usbmodem5B415328371`, `USB VID:PID=1A86:55D3 SER=5B41532837`.
- Low-level Feetech scan results after replug:
  - `/dev/cu.usbmodem5B415328371`: `found: {}`
  - `/dev/tty.usbmodem5B415328371`: `found: {}`
- Direct strict LeRobot connection still fails with the same missing motor IDs 1-6 and found motor list `{}`.
- Conclusion: the USB serial adapter/controller is visible to macOS, but the Feetech servo bus behind it is still not responding. This points to servo power, servo bus wiring, wrong controller connector, or servo ID/configuration rather than an app-level serial-port discovery issue.

## 2026-05-23 New Wiring Retry

- User rewired and asked to try again.
- Serial enumeration still shows the same controller:
  - `/dev/cu.usbmodem5B415328371`
  - `/dev/tty.usbmodem5B415328371`
  - `USB VID:PID=1A86:55D3 SER=5B41532837`
- Low-level Feetech scan results after new wiring:
  - `/dev/cu.usbmodem5B415328371`: `found: {}`
  - `/dev/tty.usbmodem5B415328371`: `found: {}`
- Strict LeRobot connect still fails with missing motor IDs 1-6 and found motor list `{}`.
- Conclusion remains unchanged: USB serial controller is visible, but no Feetech servo on the bus is responding to LeRobot's scan.

## 2026-05-23 New Driver Retry

- User swapped to a new driver and asked to try again.
- Serial enumeration now shows a different controller serial:
  - `/dev/cu.usbmodem5B7B0165961`
  - `/dev/tty.usbmodem5B7B0165961`
  - `USB VID:PID=1A86:55D3 SER=5B7B016596`
- Low-level Feetech scan results:
  - `/dev/cu.usbmodem5B7B0165961`: `found: {}`
  - `/dev/tty.usbmodem5B7B0165961`: `found: {}`
- Strict LeRobot connect on `/dev/cu.usbmodem5B7B0165961` still fails with missing motor IDs 1-6 and found motor list `{}`.
- Conclusion: the new driver is visible over USB, but still no Feetech servo responds on the bus.

## 2026-05-23 Incremental Servo Chain Retry

- User replugged the stack with only one servo connected.
- Serial enumeration still shows the new driver:
  - `/dev/cu.usbmodem5B7B0165961`
  - `/dev/tty.usbmodem5B7B0165961`
  - `USB VID:PID=1A86:55D3 SER=5B7B016596`
- Low-level Feetech scan with one servo connected:
  - `/dev/cu.usbmodem5B7B0165961`: `found: {1000000: [1]}`; scan printed model map `{1: 777}`
  - `/dev/tty.usbmodem5B7B0165961`: `found: {1000000: [1]}`; scan printed model map `{1: 777}`
- This is the first confirmed servo-bus response. The responding servo is an STS3215-compatible model `777` at ID `1`, baud `1000000`.
- User then added a second servo. Low-level Feetech scan:
  - `/dev/cu.usbmodem5B7B0165961`: `found: {1000000: [1]}`; scan printed model map `{1: 777}`
  - `/dev/tty.usbmodem5B7B0165961`: `found: {}`
- User then added four servos. Low-level Feetech scan:
  - `/dev/cu.usbmodem5B7B0165961`: `found: {}`
  - `/dev/tty.usbmodem5B7B0165961`: `found: {}`
- User then added all six servos. Low-level Feetech scan:
  - `/dev/cu.usbmodem5B7B0165961`: `found: {}`
  - `/dev/tty.usbmodem5B7B0165961`: `found: {}`
- Strict LeRobot connect with all six servos attached on `/dev/cu.usbmodem5B7B0165961` fails with missing motor IDs 1-6 and found motor list `{}`.
- Interpretation: the controller and LeRobot software path are working, because one isolated servo responds as ID `1` model `777` at baud `1000000`. Adding more servos makes the bus unstable or silent. The most likely remaining hardware/configuration causes are duplicate servo IDs, power sag under multiple servos, or a daisy-chain/cable polarity issue introduced when additional servos are connected.
- Movement commands were not attempted. With all six attached, no servo IDs respond; with a partial/ambiguous bus, motion would not validate the full arm and could mask an ID or wiring issue.
