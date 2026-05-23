from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from .ik import SimpleArmIK
from .schemas import JointPose, WorldPose
from .settings import Settings

LOGGER = logging.getLogger(__name__)


class RobotError(RuntimeError):
    pass


class RobotBackend(ABC):
    @abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_joint_pose(self, pose: JointPose, duration_s: float = 0.5) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        raise NotImplementedError


class SimRobot(RobotBackend):
    def __init__(self) -> None:
        self.connected = False
        self.joints = [0.0, -25.0, 35.0, -10.0, 0.0, 0.0]
        self.last_command_at: float | None = None

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def set_joint_pose(self, pose: JointPose, duration_s: float = 0.5) -> dict[str, Any]:
        if not self.connected:
            raise RobotError("simulation robot is not connected")
        self.joints = pose.joints
        self.last_command_at = time.time()
        return {"backend": "sim", "joints": self.joints, "duration_s": duration_s}

    def get_state(self) -> dict[str, Any]:
        return {
            "backend": "sim",
            "connected": self.connected,
            "joints": self.joints,
            "last_command_at": self.last_command_at,
        }


class LeRobotFollower(RobotBackend):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.robot: Any | None = None
        self.connected = False
        self.joint_names: list[str] = []
        self.limits = self._load_limits(settings.robot_joint_limits_json)

    @staticmethod
    def _load_limits(raw: str | None) -> list[tuple[float, float]] | None:
        if not raw:
            return None
        parsed = json.loads(raw)
        return [(float(lo), float(hi)) for lo, hi in parsed]

    def connect(self) -> None:
        if not self.settings.lerobot_port:
            raise RobotError("LEROBOT_PORT is required when ROBOT_BACKEND=lerobot")
        try:
            from lerobot.robots.so_follower import SOFollower, SOFollowerConfig
        except Exception:
            try:
                from lerobot.robots.so_follower import SO100Follower as SOFollower
                from lerobot.robots.so_follower import SO100FollowerConfig as SOFollowerConfig
            except Exception as exc:
                raise RobotError("LeRobot is not installed with SO follower support; install .[lerobot]") from exc

        config = SOFollowerConfig(
            port=self.settings.lerobot_port,
            id=self.settings.lerobot_id,
        )
        self.robot = SOFollower(config)
        self.robot.connect(calibrate=False)
        self.connected = True

    def disconnect(self) -> None:
        if self.robot is not None:
            self.robot.disconnect()
        self.connected = False

    def _clip(self, joints: list[float]) -> list[float]:
        if not self.limits:
            return joints
        clipped: list[float] = []
        for index, value in enumerate(joints):
            if index >= len(self.limits):
                clipped.append(value)
                continue
            lo, hi = self.limits[index]
            clipped.append(min(max(value, lo), hi))
        return clipped

    def set_joint_pose(self, pose: JointPose, duration_s: float = 0.5) -> dict[str, Any]:
        if not self.connected or self.robot is None:
            raise RobotError("LeRobot follower is not connected")
        joints = self._clip(pose.joints)
        action = {f"joint_{i}": value for i, value in enumerate(joints)}
        try:
            observation = self.robot.get_observation()
            if isinstance(observation, dict):
                motor_keys = [key for key in observation.keys() if "pos" in key or "joint" in key]
                if len(motor_keys) >= len(joints):
                    action = {key: joints[i] for i, key in enumerate(motor_keys[: len(joints)])}
        except Exception:
            LOGGER.debug("Could not infer LeRobot joint names from observation.", exc_info=True)
        self.robot.send_action(action)
        return {"backend": "lerobot", "action": action, "duration_s": duration_s}

    def get_state(self) -> dict[str, Any]:
        state = {"backend": "lerobot", "connected": self.connected, "port": self.settings.lerobot_port}
        if self.robot is not None and self.connected:
            try:
                state["observation"] = self.robot.get_observation()
            except Exception as exc:
                state["observation_error"] = str(exc)
        return state


class RobotController:
    def __init__(self, backend: RobotBackend, ik: SimpleArmIK | None = None) -> None:
        self.backend = backend
        self.ik = ik or SimpleArmIK()
        self.current_world_pose = WorldPose(x=0.18, y=0.0, z=0.14, pitch=-25.0)

    def connect(self) -> None:
        self.backend.connect()

    def disconnect(self) -> None:
        self.backend.disconnect()

    def set_joint_pose(self, joints: list[float], duration_s: float = 0.5) -> dict[str, Any]:
        return self.backend.set_joint_pose(JointPose(joints=joints), duration_s=duration_s)

    def set_world_pose(self, pose: WorldPose, duration_s: float = 0.5) -> dict[str, Any]:
        joint_pose = self.ik.solve(pose)
        result = self.backend.set_joint_pose(joint_pose, duration_s=duration_s)
        self.current_world_pose = pose
        result["ik_joint_pose"] = joint_pose.model_dump()
        result["world_pose"] = pose.model_dump()
        return result

    def offset_world_pose(self, **kwargs: float) -> dict[str, Any]:
        duration_s = float(kwargs.pop("duration_s", 0.5))
        pose = self.ik.offset(self.current_world_pose, **kwargs)
        return self.set_world_pose(pose, duration_s=duration_s)

    def state(self) -> dict[str, Any]:
        data = self.backend.get_state()
        data["current_world_pose"] = self.current_world_pose.model_dump()
        return data


def build_robot(settings: Settings) -> RobotController:
    backend: RobotBackend
    if settings.robot_backend == "lerobot":
        backend = LeRobotFollower(settings)
    else:
        backend = SimRobot()
    controller = RobotController(backend)
    controller.connect()
    return controller
