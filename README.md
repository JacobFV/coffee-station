# Coffee Station

## Repository status

This repository state is frozen. Future active development has moved to
[JacobFV/phys-0](https://github.com/JacobFV/phys-0); use that repository for
new work, fixes, and current project direction.

Coffee Station is a native desktop app for driving a Hugging Face LeRobot follower arm with a Gemini agent. It runs as a single window on macOS, Linux, and Windows — no browser, no server to manage.

## What it does

- Gemini tool calls for direct joint-pose control.
- IK-based world-space target and relative-offset commands.
- Scheduled bundles of tool calls with per-call time offsets.
- Queue inspection and cancellation for scheduled calls.
- Multi-camera OpenCV capture with configurable automatic frame injection into the agent loop.
- Camera scanning, enable/disable, auto-feed frequency, and latest-frame requests.
- Live camera display in the desktop window, capped by `CAMERA_FPS`.
- Local session storage in SQLite.
- Markerless monocular self-calibration for fitting arm geometry and camera extrinsics from synchronized joint/camera samples.
- A glass desktop UI with the live camera feed, conversation, queue chips, emergency stop, and a settings drawer that exposes camera, skills, queue, and developer tools.

The current default model is `gemini-flash-latest`. Override it with `GEMINI_MODEL` to pin a stable model.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run

Set your Gemini API key, then launch the app:

```bash
export GEMINI_API_KEY="..."
coffee-station
```

That's the only command. A native window opens with the camera feed and conversation. The window is the app — there is no separate process to start, no URL to visit, no port to remember.

Do not launch `coffee_station.server:create_app` with `uvicorn` for normal use or demos. The FastAPI app is an internal renderer bridge used by `coffee-station` inside the native pywebview window; running it directly leaves you with an unsupported browser/server workflow.

## Hardware configuration

Common environment variables:

```bash
export ROBOT_BACKEND=lerobot
export LEROBOT_PORT=/dev/tty.usbmodem58760431551
export LEROBOT_ID=coffee_station_arm
export LEROBOT_TYPE=so100_follower
export GEMINI_MODEL=gemini-flash-latest
```

Camera display rate:

```bash
export CAMERA_FPS=30
```

If LeRobot action keys cannot be inferred from `robot.action_features`, configure them explicitly in hardware order:

```bash
export LEROBOT_ACTION_KEYS="shoulder_pan.pos,shoulder_lift.pos,elbow_flex.pos,wrist_flex.pos,wrist_roll.pos,gripper.pos"
```

Optional safety limits are JSON `[min, max]` degree pairs matching the joint command order:

```bash
export ROBOT_JOINT_LIMITS_JSON='[[-90,90],[-90,45],[-120,120],[-120,120],[-180,180],[0,100]]'
```

If the robot cannot connect, the app refuses movement commands until LeRobot hardware is configured and reachable.

## Diagnostics

Open the settings drawer (⚙ in the top bar), expand **Developer tools**, and pick:

- `diagnose_hardware` — checks USB serial visibility and connection state.
- `scan_feetech_motors` (with a `port` argument) — verifies the servo bus. For an SO follower arm, the scan should find servo IDs `1` through `6`.

The real LeRobot backend is ready only when a USB serial arm controller is visible and `LEROBOT_PORT` points to that device.

## Tool surface

The Gemini agent and developer-tools panel expose:

- `set_joint_pose` — direct joint command in degrees, with optional `schedule_offset_s`.
- `set_world_pose` — IK target in world meters/degrees, with optional `schedule_offset_s`.
- `offset_world_pose` — IK relative move from the last world pose, with optional `schedule_offset_s`.
- `bundle_tool_calls` — schedules multiple calls using per-call `offset_s`.
- `configure_camera_feed` — enables a camera and sets automatic frame inclusion frequency.
- `discover_cameras`, `list_cameras`, `request_latest_frame`.
- `list_scheduled_actions`, `cancel_scheduled_action`, `cancel_queued_actions`.
- `start_self_calibration`, `fit_self_calibration`, `get_self_calibration`, `record_self_calibration_sample`.
- `get_robot_state`, `stop_robot`, `pause_session`, `resume_session`.

## Self-calibration

Self-calibration is feature-gated by default:

```bash
export SELF_CALIBRATION_ENABLED=true
```

The implementation persists fitted arm geometry, camera extrinsics, and calibration samples in SQLite. `start_self_calibration` commands a conservative excitation trajectory, tracks coherent webcam motion, records screen-space samples, and fits `ArmGeometry` plus camera extrinsics with bounded least-squares. `fit_self_calibration` can also fit from pre-recorded samples. On startup, persisted fitted geometry is loaded into IK for that robot id. Once fitted, agent-loop camera frames are used for FK-guided online refinement when a recent joint command is available.

## Safety

This software sends position commands to a real arm. Keep the workspace clear, use conservative joint limits in `ROBOT_JOINT_LIMITS_JSON` when needed, and keep power accessible. The included IK is a practical geometric default for SO-style 6-DOF arms; verify calibration and link lengths before using it near people or fragile objects.
