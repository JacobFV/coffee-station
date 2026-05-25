from __future__ import annotations

import time
from typing import Any, Callable

from google.genai import types

from .calibration.service import SelfCalibrationService
from .camera import CameraManager
from .hardware import diagnose_hardware, scan_feetech_motors
from .robot import RobotController
from .settings import Settings
from .schemas import CalibrationPoint, ChatMessage, ScheduledAction, ToolEnvelope, WorldPose
from .skills import SkillLibrary
from .storage import Storage


class ToolRegistry:
    def __init__(self, robot: RobotController, cameras: CameraManager, storage: Storage,
                 settings: Settings | None = None,
                 skills: SkillLibrary | None = None,
                 calibration: SelfCalibrationService | None = None) -> None:
        self.robot = robot
        self.cameras = cameras
        self.storage = storage
        self.settings = settings or Settings()
        self.skills = skills or SkillLibrary()
        self.calibration = calibration
        self._tools: dict[str, Callable[..., dict[str, Any]]] = {
            "set_joint_pose": self.set_joint_pose,
            "set_world_pose": self.set_world_pose,
            "offset_world_pose": self.offset_world_pose,
            "bundle_tool_calls": self.bundle_tool_calls,
            "configure_camera_feed": self.configure_camera_feed,
            "request_latest_frame": self.request_latest_frame,
            "list_cameras": self.list_cameras,
            "discover_cameras": self.discover_cameras,
            "get_robot_state": self.get_robot_state,
            "diagnose_hardware": self.diagnose_hardware,
            "scan_feetech_motors": self.scan_feetech_motors,
            "stop_robot": self.stop_robot,
            "list_scheduled_actions": self.list_scheduled_actions,
            "cancel_scheduled_action": self.cancel_scheduled_action,
            "cancel_queued_actions": self.cancel_queued_actions,
            "list_agent_skills": self.list_agent_skills,
            "activate_agent_skill": self.activate_agent_skill,
            "record_calibration_point": self.record_calibration_point,
            "get_calibration": self.get_calibration,
            "clear_calibration": self.clear_calibration,
            "start_self_calibration": self.start_self_calibration,
            "fit_self_calibration": self.fit_self_calibration,
            "get_self_calibration": self.get_self_calibration,
            "record_self_calibration_sample": self.record_self_calibration_sample,
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
                description="List currently configured camera devices, frame status, and automatic agent-loop feed settings.",
                parameters={"type": "object", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="discover_cameras",
                description="Scan local device camera indexes and add available cameras to the configurable device list.",
                parameters={"type": "object", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="get_robot_state",
                description="Return the current robot backend state, latest world pose, queued movement context, and connection status.",
                parameters={"type": "object", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="diagnose_hardware",
                description="Report configured robot backend, visible serial ports, macOS USB summary, and whether LeRobot has a usable port.",
                parameters={"type": "object", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="scan_feetech_motors",
                description="Scan a serial port for Feetech servo IDs using LeRobot's low-level bus scan.",
                parameters={
                    "type": "object",
                    "properties": {"port": {"type": "string"}},
                    "required": ["port"],
                },
            ),
            types.FunctionDeclaration(
                name="stop_robot",
                description="Immediately stop the robot backend when supported. On basic LeRobot backends this may disconnect the robot.",
                parameters={"type": "object", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="list_scheduled_actions",
                description="List queued and recent scheduled actions for this session.",
                parameters={"type": "object", "properties": {"limit": {"type": "integer"}}},
            ),
            types.FunctionDeclaration(
                name="cancel_scheduled_action",
                description="Cancel one queued scheduled action by id.",
                parameters={
                    "type": "object",
                    "properties": {"action_id": {"type": "string"}},
                    "required": ["action_id"],
                },
            ),
            types.FunctionDeclaration(
                name="cancel_queued_actions",
                description="Cancel all queued scheduled actions for this session.",
                parameters={"type": "object", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="list_agent_skills",
                description="List high-level procedural skills available to the arm agent.",
                parameters={"type": "object", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="activate_agent_skill",
                description="Load the full instructions for one high-level procedural skill.",
                parameters={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            ),
            types.FunctionDeclaration(
                name="record_calibration_point",
                description="Record a comparison between believed commanded gripper coordinates and measured actual gripper coordinates.",
                parameters={
                    "type": "object",
                    "properties": {
                        "believed_x": {"type": "number"},
                        "believed_y": {"type": "number"},
                        "believed_z": {"type": "number"},
                        "actual_x": {"type": "number"},
                        "actual_y": {"type": "number"},
                        "actual_z": {"type": "number"},
                        "note": {"type": "string"},
                    },
                    "required": ["believed_x", "believed_y", "believed_z", "actual_x", "actual_y", "actual_z"],
                },
            ),
            types.FunctionDeclaration(
                name="get_calibration",
                description="Return calibration comparison points and the current mean XYZ actual-minus-believed offset.",
                parameters={"type": "object", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="clear_calibration",
                description="Clear all calibration comparison points for this session.",
                parameters={"type": "object", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="start_self_calibration",
                description="Run markerless monocular self-calibration using the camera and a safe excitation trajectory. Requires SELF_CALIBRATION_ENABLED.",
                parameters={
                    "type": "object",
                    "properties": {
                        "camera_id": {"type": "integer"},
                        "duration_s": {"type": "number"},
                    },
                },
            ),
            types.FunctionDeclaration(
                name="fit_self_calibration",
                description="Fit arm geometry and camera extrinsics from already recorded monocular calibration samples.",
                parameters={"type": "object", "properties": {"camera_id": {"type": "integer"}}},
            ),
            types.FunctionDeclaration(
                name="get_self_calibration",
                description="Return fitted arm geometry, camera extrinsics, confidence, and feature-gate status.",
                parameters={"type": "object", "properties": {"camera_id": {"type": "integer"}}},
            ),
            types.FunctionDeclaration(
                name="record_self_calibration_sample",
                description="Record one synchronized joint-vector to screen-space gripper observation for solver-driven self-calibration.",
                parameters={
                    "type": "object",
                    "properties": {
                        "camera_id": {"type": "integer"},
                        "joint_vector": {"type": "array", "items": {"type": "number"}},
                        "pixel_u": {"type": "number"},
                        "pixel_v": {"type": "number"},
                        "frame_width": {"type": "integer"},
                        "frame_height": {"type": "integer"},
                        "tracker_confidence": {"type": "number"},
                    },
                    "required": ["camera_id", "joint_vector", "pixel_u", "pixel_v", "frame_width", "frame_height"],
                },
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
        immediate_only = {
            "bundle_tool_calls",
            "configure_camera_feed",
            "request_latest_frame",
            "list_cameras",
            "discover_cameras",
            "get_robot_state",
            "diagnose_hardware",
            "scan_feetech_motors",
            "stop_robot",
            "list_scheduled_actions",
            "cancel_scheduled_action",
            "cancel_queued_actions",
            "list_agent_skills",
            "activate_agent_skill",
            "record_calibration_point",
            "get_calibration",
            "clear_calibration",
            "start_self_calibration",
            "fit_self_calibration",
            "get_self_calibration",
            "record_self_calibration_sample",
            "pause_session",
            "resume_session",
        }
        if schedule_offset_s > 0 and tool_name not in immediate_only:
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
            self.storage.update_action_status(action.id, "running")
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
        return {"cameras": self.cameras.status()}

    def discover_cameras(self, session_id: str) -> dict[str, Any]:
        discovered = self.cameras.discover()
        for config in self.cameras.list_agent_configs():
            self.storage.upsert_camera_config(session_id, config)
        return {"discovered": discovered, "cameras": self.cameras.status()}

    def get_robot_state(self, session_id: str) -> dict[str, Any]:
        return self.robot.state()

    def diagnose_hardware(self, session_id: str) -> dict[str, Any]:
        return diagnose_hardware(self.settings)

    def scan_feetech_motors(self, session_id: str, port: str) -> dict[str, Any]:
        return scan_feetech_motors(port)

    def stop_robot(self, session_id: str) -> dict[str, Any]:
        canceled = self.storage.cancel_queued_actions(session_id)
        result = self.robot.stop()
        result["canceled_queued_actions"] = canceled
        return result

    def list_scheduled_actions(self, session_id: str, limit: int = 100) -> dict[str, Any]:
        return {"actions": [action.model_dump() for action in self.storage.list_actions(session_id, limit=limit)]}

    def cancel_scheduled_action(self, session_id: str, action_id: str) -> dict[str, Any]:
        action = self.storage.cancel_action(action_id)
        return {"action": None if action is None else action.model_dump()}

    def cancel_queued_actions(self, session_id: str) -> dict[str, Any]:
        return {"canceled": self.storage.cancel_queued_actions(session_id)}

    def list_agent_skills(self, session_id: str) -> dict[str, Any]:
        return {"skills": [{"name": skill.name, "description": skill.description} for skill in self.skills.list()]}

    def activate_agent_skill(self, session_id: str, name: str) -> dict[str, Any]:
        skill = self.skills.get(name)
        if skill is None:
            raise ValueError(f"unknown skill: {name}")
        return {"skill": {"name": skill.name, "description": skill.description, "instructions": skill.body.strip()}}

    def record_calibration_point(
        self,
        session_id: str,
        believed_x: float,
        believed_y: float,
        believed_z: float,
        actual_x: float,
        actual_y: float,
        actual_z: float,
        note: str | None = None,
    ) -> dict[str, Any]:
        point = self.storage.add_calibration_point(
            CalibrationPoint(
                session_id=session_id,
                believed_x=believed_x,
                believed_y=believed_y,
                believed_z=believed_z,
                actual_x=actual_x,
                actual_y=actual_y,
                actual_z=actual_z,
                note=note,
            )
        )
        return {"point": point.model_dump(), "calibration": self._calibration_summary(session_id)}

    def get_calibration(self, session_id: str) -> dict[str, Any]:
        return self._calibration_summary(session_id)

    def clear_calibration(self, session_id: str) -> dict[str, Any]:
        return {"cleared": self.storage.clear_calibration_points(session_id)}

    def _require_self_calibration(self) -> SelfCalibrationService:
        if self.calibration is None:
            raise RuntimeError("self-calibration service is not configured")
        return self.calibration

    def start_self_calibration(
        self,
        session_id: str,
        camera_id: int = 0,
        duration_s: float = 0.35,
    ) -> dict[str, Any]:
        result = self._require_self_calibration().start_markerless_calibration(session_id, camera_id, duration_s)
        return {"result": result.model_dump()}

    def fit_self_calibration(self, session_id: str, camera_id: int = 0) -> dict[str, Any]:
        result = self._require_self_calibration().fit_from_session_samples(session_id, camera_id)
        return {"result": result.model_dump()}

    def get_self_calibration(self, session_id: str, camera_id: int = 0) -> dict[str, Any]:
        del session_id
        return self._require_self_calibration().status(camera_id)

    def record_self_calibration_sample(
        self,
        session_id: str,
        camera_id: int,
        joint_vector: list[float],
        pixel_u: float,
        pixel_v: float,
        frame_width: int,
        frame_height: int,
        tracker_confidence: float = 1.0,
    ) -> dict[str, Any]:
        sample = self._require_self_calibration().record_sample(
            session_id=session_id,
            camera_id=camera_id,
            joint_vector=joint_vector,
            pixel_u=pixel_u,
            pixel_v=pixel_v,
            frame_width=frame_width,
            frame_height=frame_height,
            tracker_confidence=tracker_confidence,
        )
        return {"sample": sample.model_dump()}

    def _calibration_summary(self, session_id: str) -> dict[str, Any]:
        points = self.storage.list_calibration_points(session_id)
        if not points:
            return {
                "sample_count": 0,
                "offset": {"x": 0.0, "y": 0.0, "z": 0.0},
                "points": [],
                "guidance": "No calibration points recorded. Use record_calibration_point.",
            }
        dx = sum(point.actual_x - point.believed_x for point in points) / len(points)
        dy = sum(point.actual_y - point.believed_y for point in points) / len(points)
        dz = sum(point.actual_z - point.believed_z for point in points) / len(points)
        return {
            "sample_count": len(points),
            "offset": {"x": dx, "y": dy, "z": dz},
            "compensation_rule": "For a real target, command target minus this offset.",
            "points": [point.model_dump() for point in points],
        }

    def pause_session(self, session_id: str) -> dict[str, Any]:
        self.storage.update_session_status(session_id, "paused")
        return {"status": "paused"}

    def resume_session(self, session_id: str) -> dict[str, Any]:
        self.storage.update_session_status(session_id, "running")
        return {"status": "running"}
