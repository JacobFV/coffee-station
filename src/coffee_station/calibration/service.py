from __future__ import annotations

import time
from typing import Any, Literal

from coffee_station.camera import CameraManager
from coffee_station.camera import CapturedFrame
from coffee_station.robot import RobotController
from coffee_station.settings import Settings
from coffee_station.storage import Storage

from .excitation import excitation_joint_poses
from .geometry import forward_kinematics_tip, project_point
from .models import CalibrationFitResult, CalibrationSample, CameraIntrinsics
from .solver import CalibrationSolverError, MonocularCalibrationSolver, default_extrinsics
from .tracker import MarkerlessMotionTracker


class SelfCalibrationService:
    def __init__(self, settings: Settings, storage: Storage, robot: RobotController, cameras: CameraManager) -> None:
        self.settings = settings
        self.storage = storage
        self.robot = robot
        self.cameras = cameras
        self.trackers: dict[int, MarkerlessMotionTracker] = {}

    @property
    def robot_id(self) -> str:
        return self.settings.lerobot_id if self.settings.robot_backend == "lerobot" else "sim"

    def status(self, camera_id: int = 0) -> dict[str, Any]:
        arm = self.storage.get_arm_calibration(self.robot_id)
        camera = self.storage.get_camera_extrinsics(camera_id)
        return {
            "enabled": self.settings.self_calibration_enabled,
            "robot_id": self.robot_id,
            "arm": None if arm is None else arm.model_dump(),
            "camera": None if camera is None else camera.model_dump(),
            "confidence": self._confidence(arm, camera),
        }

    def fit_from_session_samples(self, session_id: str, camera_id: int = 0) -> CalibrationFitResult:
        samples = self.storage.list_calibration_samples(session_id, camera_id=camera_id)
        if not samples:
            raise CalibrationSolverError("no self-calibration samples are available for this session")
        intrinsics = CameraIntrinsics.from_frame(samples[0].frame_width, samples[0].frame_height)
        solver = MonocularCalibrationSolver(self.robot_id, self.robot.ik.geometry)
        result = solver.fit(
            samples,
            intrinsics=intrinsics,
            initial_extrinsics=self.storage.get_camera_extrinsics(camera_id) or default_extrinsics(camera_id),
        )
        self.storage.save_arm_calibration(result.arm)
        self.storage.save_camera_extrinsics(result.camera)
        self.robot.apply_calibration(result.arm)
        return result

    def start_markerless_calibration(
        self,
        session_id: str,
        camera_id: int = 0,
        duration_s: float = 0.35,
    ) -> CalibrationFitResult:
        if not self.settings.self_calibration_enabled:
            raise CalibrationSolverError("SELF_CALIBRATION_ENABLED must be true to command calibration motion")
        self.storage.clear_calibration_samples(session_id, camera_id=camera_id)
        tracker = MarkerlessMotionTracker()
        captured = 0
        for joints in excitation_joint_poses():
            self.robot.set_joint_pose(joints, duration_s=duration_s)
            time.sleep(max(0.05, min(duration_s, 1.0)))
            frame = self.cameras.raw_frame(camera_id, refresh=True)
            if frame is None:
                continue
            point = tracker.observe(frame.jpeg)
            if point is None:
                continue
            self.storage.add_calibration_sample(
                CalibrationSample(
                    session_id=session_id,
                    camera_id=camera_id,
                    timestamp=frame.timestamp,
                    joint_vector=joints,
                    pixel_u=point.u,
                    pixel_v=point.v,
                    frame_width=frame.width,
                    frame_height=frame.height,
                    tracker_confidence=point.confidence,
                    source="tracker",
                )
            )
            captured += 1
        if captured < self.settings.self_calibration_min_samples:
            raise CalibrationSolverError(
                f"captured {captured} usable samples; need at least {self.settings.self_calibration_min_samples}"
            )
        return self.fit_from_session_samples(session_id, camera_id=camera_id)

    def observe_agent_frame(self, session_id: str, frame: CapturedFrame) -> CalibrationSample | None:
        if not self.settings.self_calibration_enabled:
            return None
        arm = self.storage.get_arm_calibration(self.robot_id)
        camera = self.storage.get_camera_extrinsics(frame.camera_id)
        if arm is None or camera is None or arm.status != "fit":
            return None
        recent = self.robot.recent_joint_pose(max_age_s=5.0)
        if recent is None:
            return None
        _commanded_at, joints = recent
        intrinsics = CameraIntrinsics.from_frame(frame.width, frame.height)
        expected_uv = project_point(forward_kinematics_tip(joints, arm.geometry(), arm.joint_zero_offsets_deg), intrinsics, camera)
        tracker = self.trackers.setdefault(frame.camera_id, MarkerlessMotionTracker())
        point = tracker.observe(frame.jpeg, expected_uv=expected_uv)
        if point is None:
            return None
        sample = self.record_sample(
            session_id=session_id,
            camera_id=frame.camera_id,
            joint_vector=joints,
            pixel_u=point.u,
            pixel_v=point.v,
            frame_width=frame.width,
            frame_height=frame.height,
            tracker_confidence=point.confidence,
            source="tracker",
            timestamp=frame.timestamp,
        )
        samples = self.storage.list_calibration_samples(session_id, camera_id=frame.camera_id)
        if len(samples) >= self.settings.self_calibration_min_samples:
            result = self.fit_from_session_samples(session_id, frame.camera_id)
            self.robot.apply_calibration(result.arm)
        return sample

    def record_sample(
        self,
        session_id: str,
        camera_id: int,
        joint_vector: list[float],
        pixel_u: float,
        pixel_v: float,
        frame_width: int,
        frame_height: int,
        tracker_confidence: float = 1.0,
        source: Literal["tracker", "manual", "synthetic"] = "manual",
        timestamp: float | None = None,
    ) -> CalibrationSample:
        sample = CalibrationSample(
            session_id=session_id,
            camera_id=camera_id,
            timestamp=timestamp if timestamp is not None else time.time(),
            joint_vector=joint_vector,
            pixel_u=pixel_u,
            pixel_v=pixel_v,
            frame_width=frame_width,
            frame_height=frame_height,
            tracker_confidence=tracker_confidence,
            source=source,
        )
        return self.storage.add_calibration_sample(sample)

    @staticmethod
    def _confidence(arm: Any, camera: Any) -> dict[str, Any]:
        if arm is None or camera is None:
            return {"status": "unfit", "sample_count": 0, "residual_rms_px": None}
        residuals = [value for value in (arm.residual_rms_px, camera.residual_rms_px) if value is not None]
        residual = max(residuals) if residuals else None
        if residual is None:
            status = "unknown"
        elif residual <= 3.0:
            status = "high"
        elif residual <= 8.0:
            status = "medium"
        else:
            status = "low"
        return {
            "status": status,
            "sample_count": min(arm.sample_count, camera.sample_count),
            "residual_rms_px": residual,
            "updated_at": max(arm.updated_at, camera.updated_at).isoformat(),
        }
