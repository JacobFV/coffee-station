# Coffee Station

Coffee Station is a local Python desktop harness for a USB Hugging Face LeRobot follower arm controlled by Gemini function calls. It includes:

- Gemini tool calls for direct joint-pose control.
- IK-based world-space target and relative-offset tool calls.
- Scheduled bundles of tool calls with per-call time offsets.
- Queue inspection and cancellation for scheduled calls.
- Multi-camera OpenCV capture with configurable automatic frame injection into the agent loop.
- Camera device scanning, enable/disable, auto-feed frequency, and latest-frame requests.
- Realtime MJPEG camera display in the desktop UI, capped by `CAMERA_FPS`.
- Manual latest-frame requests.
- Local session storage in SQLite.
- A local desktop-style UI with the active camera feed, session controls, queue controls, manual tool execution, pause/resume, robot stop, and an autonomous agent chat sidebar.

The current default model is `gemini-flash-latest`, which follows Google AI's latest Flash alias. Override it with `GEMINI_MODEL` when you want a pinned stable model.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

For physical LeRobot hardware:

```bash
pip install -e ".[lerobot]"
```

Set your Gemini API key:

```bash
export GEMINI_API_KEY="..."
```

Run the desktop app:

```bash
coffee-station
```

This opens Coffee Station in a native desktop window. The app uses the simulation robot backend unless a LeRobot port is configured.

Development server mode is still available:

```bash
coffee-station --server
```

Browser mode is also available:

```bash
coffee-station --browser
```

## Hardware Configuration

Common environment variables:

```bash
export ROBOT_BACKEND=lerobot
export LEROBOT_PORT=/dev/tty.usbmodem58760431551
export LEROBOT_ID=coffee_station_arm
export LEROBOT_TYPE=so100_follower
export GEMINI_MODEL=gemini-flash-latest
```

Camera display rate is controlled by `CAMERA_FPS` and the UI feed setting:

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

If the robot cannot connect, the app refuses movement commands for the LeRobot backend. Use `ROBOT_BACKEND=sim` for development without hardware.

Use the built-in diagnostics before enabling the physical backend:

```bash
curl http://127.0.0.1:8765/api/hardware/diagnostics
```

The desktop UI also exposes `diagnose_hardware` in the manual tool panel. The real LeRobot backend is ready only when a USB serial arm controller is visible and `LEROBOT_PORT` points to that device.

## Tool Surface

The Gemini harness and UI expose these tools:

- `set_joint_pose`: direct joint command in degrees, with optional `schedule_offset_s`.
- `set_world_pose`: IK target in world meters/degrees, with optional `schedule_offset_s`.
- `offset_world_pose`: IK relative move from the last world pose, with optional `schedule_offset_s`.
- `bundle_tool_calls`: schedules multiple calls using per-call `offset_s`.
- `configure_camera_feed`: enables a camera and sets automatic frame inclusion frequency.
- `discover_cameras`, `list_cameras`, `request_latest_frame`.
- `list_scheduled_actions`, `cancel_scheduled_action`, `cancel_queued_actions`.
- `get_robot_state`, `stop_robot`, `pause_session`, `resume_session`.

## Safety

This software sends position commands to a real arm. Keep the workspace clear, use conservative joint limits in `ROBOT_JOINT_LIMITS_JSON` when needed, and keep power accessible. The included IK is a practical geometric default for SO-style 6-DOF arms; verify calibration and link lengths before using it near people or fragile objects.
