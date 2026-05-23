from __future__ import annotations

import time
from typing import Any, Callable

from google.genai import types

from .camera import CameraManager
from .robot import RobotController
from .schemas import ChatMessage, ScheduledAction, ToolEnvelope, WorldPose
from .storage import Storage


class ToolRegistry:
    def __init__(self, robot: RobotController, cameras: CameraManager, storage: Storage) -> None:
        self.robot = robot
        self.cameras = cameras
        self.storage = storage
        self._tools: dict[str, Callable[..., dict[str, Any]]] = {
            "set_joint_pose": self.set_joint_pose,
            "set_world_pose": self.set_world_pose,
            "offset_world_pose": self.offset_world_pose,
            "bundle_tool_calls": self.bundle_tool_calls,
            "configure_camera_feed": self.configure_camera_feed,
            "request_latest_frame": self.request_latest_frame,
            "list_cameras": self.list_cameras,
            "get_robot_state": self.get_robot_state,
            "pause_session": self.pause_session,
            "resume_session": self.resume_session,
        }

    @property
    def declarations(self) -> list[types.FunctionDeclaration]:
        return [
            types.FunctionDeclaration(
                name="set_joint_pose",
                description="Directly command the LeRobot arm by joint pose. Values are degrees and include the gripper if available. Can be scheduled with schedule_offset_s.",
                parameters={
                    "type": "object",
                    "properties": {
                        "joints": {"type": "array", "items": {"type": "number"}},
                        "duration_s": {"type": "number"},
                        "schedule_offset_s": {"type": "number"},
                    },
                    "required": ["joints"],
                },
            ),
            types.FunctionDeclaration(
                name="set_world_pose",
                description="Use IK to move the end effector to a world-space pose in meters and degrees. Can be scheduled with schedule_offset_s.",
                parameters={
                    "type": "object",
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "z": {"type": "number"},
                        "roll": {"type": "number"},
                        "pitch": {"type": "number"},
                        "yaw": {"type": "number"},
                        "gripper": {"type": "number"},
                        "duration_s": {"type": "number"},
                        "schedule_offset_s": {"type": "number"},
                    },
                    "required": ["x", "y", "z"],
                },
            ),
            types.FunctionDeclaration(
                name="offset_world_pose",
                description="Use IK to move relative to the last world-space pose. Offsets are meters and degrees. Can be scheduled with schedule_offset_s.",
                parameters={
                    "type": "object",
                    "properties": {
                        "dx": {"type": "number"},
                        "dy": {"type": "number"},
                        "dz": {"type": "number"},
                        "droll": {"type": "number"},
                        "dpitch": {"type": "number"},
                        "dyaw": {"type": "number"},
                        "gripper": {"type": "number"},
                        "duration_s": {"type": "number"},
                        "schedule_offset_s": {"type": "number"},
                    },
                },
            ),
            types.FunctionDeclaration(
                name="bundle_tool_calls",
                description="Schedule several tool calls together. Each call has tool_name, args, and offset_s relative to now.",
                parameters={
                    "type": "object",
                    "properties": {
                        "calls": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "tool_name": {"type": "string"},
                                    "args": {"type": "object"},
                                    "offset_s": {"type": "number"},
                                },
                                "required": ["tool_name", "args"],
                            },
                        }
                    },
                    "required": ["calls"],
                },
            ),
            types.FunctionDeclaration(
                name="configure_camera_feed",
                description="Enable a connected camera and configure whether/frequency frames are automatically included in each agent loop.",
                parameters={
                    "type": "object",
                    "properties": {
                        "camera_id": {"type": "integer"},
                        "enabled": {"type": "boolean"},
                        "auto_include": {"type": "boolean"},
                        "frequency_hz": {"type": "number"},
                        "label": {"type": "string"},
                    },
                    "required": ["camera_id"],
                },
            ),
            types.FunctionDeclaration(
                name="request_latest_frame",
                description="Manually request the latest frame from a camera. Returns metadata and a base64 JPEG for tool feedback.",
                parameters={
                    "type": "object",
                    "properties": {"camera_id": {"type": "integer"}, "refresh": {"type": "boolean"}},
                    "required": ["camera_id"],
                },
            ),
            types.FunctionDeclaration(
                name="list_cameras",
                description="List currently configured camera devices and automatic agent-loop feed settings.",
                parameters={"type": "object", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="get_robot_state",
                description="Return the current robot backend state, latest world pose, queued movement context, and connection status.",
                parameters={"type": "object", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="pause_session",
                description="Pause autonomous agent steps for this session. Already scheduled robot actions may continue if due.",
                parameters={"type": "object", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="resume_session",
                description="Resume autonomous agent steps for this session.",
                parameters={"type": "object", "properties": {}},
            ),
        ]

    def dispatch(self, session_id: str, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool_name not in self._tools:
            raise ValueError(f"unknown tool: {tool_name}")
        schedule_offset_s = float(args.pop("schedule_offset_s", 0.0) or 0.0)
        if schedule_offset_s > 0 and tool_name not in {"bundle_tool_calls", "configure_camera_feed", "request_latest_frame", "list_cameras", "get_robot_state", "pause_session", "resume_session"}:
            action = self.schedule(session_id, tool_name, args, schedule_offset_s)
            return {"scheduled": action.model_dump()}
        return self._tools[tool_name](session_id=session_id, **args)

    def schedule(self, session_id: str, tool_name: str, args: dict[str, Any], offset_s: float) -> ScheduledAction:
        now = time.time()
        action = ScheduledAction(
            session_id=session_id,
            tool_name=tool_name,
            args=args,
            due_at=now + max(0.0, offset_s),
            created_at=now,
        )
        return self.storage.save_action(action)

    def run_due_actions(self) -> list[ScheduledAction]:
        due = self.storage.due_actions(time.time())
        completed: list[ScheduledAction] = []
        for action in due:
            action.status = "running"
            self.storage.save_action(action)
            try:
                action.result = self.dispatch(action.session_id, action.tool_name, dict(action.args))
                action.status = "done"
            except Exception as exc:
                action.status = "failed"
                action.error = str(exc)
            self.storage.save_action(action)
            self.storage.add_message(
                action.session_id,
                ChatMessage(role="tool", content=f"{action.tool_name}: {action.status}", metadata=action.model_dump()),
            )
            completed.append(action)
        return completed

    def set_joint_pose(self, session_id: str, joints: list[float], duration_s: float = 0.5) -> dict[str, Any]:
        return self.robot.set_joint_pose(joints, duration_s=duration_s)

    def set_world_pose(self, session_id: str, x: float, y: float, z: float, roll: float = 0.0,
                       pitch: float = 0.0, yaw: float = 0.0, gripper: float | None = None,
                       duration_s: float = 0.5) -> dict[str, Any]:
        return self.robot.set_world_pose(
            WorldPose(x=x, y=y, z=z, roll=roll, pitch=pitch, yaw=yaw, gripper=gripper),
            duration_s=duration_s,
        )

    def offset_world_pose(self, session_id: str, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0,
                          droll: float = 0.0, dpitch: float = 0.0, dyaw: float = 0.0,
                          gripper: float | None = None, duration_s: float = 0.5) -> dict[str, Any]:
        return self.robot.offset_world_pose(
            dx=dx,
            dy=dy,
            dz=dz,
            droll=droll,
            dpitch=dpitch,
            dyaw=dyaw,
            gripper=gripper,
            duration_s=duration_s,
        )

    def bundle_tool_calls(self, session_id: str, calls: list[dict[str, Any]]) -> dict[str, Any]:
        scheduled = []
        for raw in calls:
            envelope = ToolEnvelope(**raw)
            scheduled.append(self.schedule(session_id, envelope.tool_name, envelope.args, envelope.offset_s).model_dump())
        return {"scheduled": scheduled}

    def configure_camera_feed(self, session_id: str, camera_id: int, enabled: bool | None = None,
                              auto_include: bool | None = None, frequency_hz: float | None = None,
                              label: str | None = None) -> dict[str, Any]:
        result = self.cameras.configure(camera_id, enabled, auto_include, frequency_hz, label)
        config = next(c for c in self.cameras.list_configs() if c.camera_id == camera_id)
        self.storage.upsert_camera_config(session_id, config)
        return result

    def request_latest_frame(self, session_id: str, camera_id: int, refresh: bool = True) -> dict[str, Any]:
        frame = self.cameras.latest_frame(camera_id, include_bytes=True, refresh=refresh)
        return {"frame": None if frame is None else frame.model_dump()}

    def list_cameras(self, session_id: str) -> dict[str, Any]:
        return {"cameras": [config.model_dump() for config in self.cameras.list_configs()]}

    def get_robot_state(self, session_id: str) -> dict[str, Any]:
        return self.robot.state()

    def pause_session(self, session_id: str) -> dict[str, Any]:
        self.storage.update_session_status(session_id, "paused")
        return {"status": "paused"}

    def resume_session(self, session_id: str) -> dict[str, Any]:
        self.storage.update_session_status(session_id, "running")
        return {"status": "running"}
