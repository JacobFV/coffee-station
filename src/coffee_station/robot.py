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
    def stop(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        raise NotImplementedError


class SimRobot(RobotBackend):
    def __init__(self, limits: list[tuple[float, float]] | None = None, min_command_interval_s: float = 0.05) -> None:
        self.connected = False
        self.joints = [0.0, -25.0, 35.0, -10.0, 0.0, 0.0]
        self.last_command_at: float | None = None
        self.limits = limits
        self.min_command_interval_s = min_command_interval_s

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def set_joint_pose(self, pose: JointPose, duration_s: float = 0.5) -> dict[str, Any]:
        if not self.connected:
            raise RobotError("simulation robot is not connected")
        self._rate_limit()
        self.joints = self._clip(pose.joints)
        self.last_command_at = time.time()
        return {"backend": "sim", "joints": self.joints, "duration_s": duration_s}

    def stop(self) -> dict[str, Any]:
        return {"backend": "sim", "stopped": True, "joints": self.joints}

    def get_state(self) -> dict[str, Any]:
        return {
            "backend": "sim",
            "connected": self.connected,
            "joints": self.joints,
            "last_command_at": self.last_command_at,
        }

    def _clip(self, joints: list[float]) -> list[float]:
        if not self.limits:
            return joints
        clipped: list[float] = []
        for index, value in enumerate(joints):
            if index < len(self.limits):
                lo, hi = self.limits[index]
                clipped.append(min(max(value, lo), hi))
            else:
                clipped.append(value)
        return clipped

    def _rate_limit(self) -> None:
        if self.last_command_at is None:
            return
        elapsed = time.time() - self.last_command_at
        wait_s = self.min_command_interval_s - elapsed
        if wait_s > 0:
            time.sleep(wait_s)


class LeRobotFollower(RobotBackend):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.robot: Any | None = None
        self.connected = False
        self.joint_names: list[str] = []
        self.limits = self._load_limits(settings.robot_joint_limits_json)
        self.last_command_at: float | None = None
        self.action_keys = self._configured_action_keys(settings.lerobot_action_keys)

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
        self.action_keys = self.action_keys or self._infer_action_keys()
        self.connected = True

    @staticmethod
    def _configured_action_keys(raw: str | None) -> list[str]:
        if not raw:
            return []
        return [part.strip() for part in raw.split(",") if part.strip()]

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

    def _rate_limit(self) -> None:
        if self.last_command_at is None:
            return
        elapsed = time.time() - self.last_command_at
        wait_s = self.settings.robot_min_command_interval_s - elapsed
        if wait_s > 0:
            time.sleep(wait_s)

    def _infer_action_keys(self) -> list[str]:
        if self.robot is None:
            return []
        action_features = getattr(self.robot, "action_features", None)
        if isinstance(action_features, dict) and action_features:
            return list(action_features.keys())
        action_feature_names = getattr(action_features, "keys", None)
        if callable(action_feature_names):
            return list(action_feature_names())
        observation_type = getattr(self.robot, "observation_features", None)
        if isinstance(observation_type, dict):
            keys = [key for key in observation_type if self._looks_like_motor_key(key)]
            if keys:
                return keys
        try:
            observation = self.robot.get_observation()
        except Exception:
            return []
        if isinstance(observation, dict):
            return [key for key in observation if self._looks_like_motor_key(key)]
        return []

    @staticmethod
    def _looks_like_motor_key(key: str) -> bool:
        lowered = key.lower()
        if "image" in lowered or "camera" in lowered:
            return False
        return any(token in lowered for token in ("pos", "joint", "motor", "servo", "gripper", "shoulder", "elbow", "wrist"))

    def _make_action(self, joints: list[float]) -> dict[str, float]:
        if self.action_keys:
            if len(self.action_keys) < len(joints):
                raise RobotError(
                    f"configured LeRobot action key count ({len(self.action_keys)}) is lower than joint count ({len(joints)})"
                )
            return {key: joints[index] for index, key in enumerate(self.action_keys[: len(joints)])}
        return {f"joint_{i}": value for i, value in enumerate(joints)}

    def set_joint_pose(self, pose: JointPose, duration_s: float = 0.5) -> dict[str, Any]:
        if not self.connected or self.robot is None:
            raise RobotError("LeRobot follower is not connected")
        self._rate_limit()
        joints = self._clip(pose.joints)
        action = self._make_action(joints)
        self.robot.send_action(action)
        self.last_command_at = time.time()
        return {"backend": "lerobot", "action": action, "duration_s": duration_s, "action_keys": list(action.keys())}

    def stop(self) -> dict[str, Any]:
        if not self.connected or self.robot is None:
            raise RobotError("LeRobot follower is not connected")
        if hasattr(self.robot, "stop"):
            self.robot.stop()
            return {"backend": "lerobot", "stopped": True, "method": "stop"}
        if hasattr(self.robot, "disconnect"):
            self.robot.disconnect()
            self.connected = False
            return {"backend": "lerobot", "stopped": True, "method": "disconnect"}
        return {"backend": "lerobot", "stopped": False, "reason": "no stop or disconnect method available"}

    def get_state(self) -> dict[str, Any]:
        state = {
            "backend": "lerobot",
            "connected": self.connected,
            "port": self.settings.lerobot_port,
            "action_keys": self.action_keys,
            "last_command_at": self.last_command_at,
        }
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

    def stop(self) -> dict[str, Any]:
        return self.backend.stop()

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
    limits = LeRobotFollower._load_limits(settings.robot_joint_limits_json)
    if settings.robot_backend == "lerobot":
        backend = LeRobotFollower(settings)
    else:
        backend = SimRobot(limits=limits, min_command_interval_s=settings.robot_min_command_interval_s)
    controller = RobotController(backend)
    controller.connect()
    return controller
