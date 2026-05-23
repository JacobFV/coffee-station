# Coffee Station

Coffee Station is a local Python desktop harness for a USB Hugging Face LeRobot follower arm controlled by Gemini function calls. It includes:

- Gemini tool calls for direct joint-pose control.
- IK-based world-space target and relative-offset tool calls.
- Scheduled bundles of tool calls with per-call time offsets.
- Multi-camera OpenCV capture with configurable automatic frame injection into the agent loop.
- Manual latest-frame requests.
- Local session storage in SQLite.
- A local desktop-style UI with the active camera feed, session controls, pause/resume, and an autonomous agent chat sidebar.

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

Run the app:

```bash
coffee-station
```

Open the printed local URL. The app uses the simulation robot backend unless a LeRobot port is configured.

## Hardware Configuration

Common environment variables:

```bash
export ROBOT_BACKEND=lerobot
export LEROBOT_PORT=/dev/tty.usbmodem58760431551
export LEROBOT_ID=coffee_station_arm
export LEROBOT_TYPE=so100_follower
export GEMINI_MODEL=gemini-flash-latest
```

If the robot cannot connect, the app refuses movement commands for the LeRobot backend. Use `ROBOT_BACKEND=sim` for development without hardware.

## Safety

This software sends position commands to a real arm. Keep the workspace clear, use conservative joint limits in `ROBOT_JOINT_LIMITS_JSON` when needed, and keep power accessible. The included IK is a practical geometric default for SO-style 6-DOF arms; verify calibration and link lengths before using it near people or fragile objects.
