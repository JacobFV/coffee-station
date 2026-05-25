from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from coffee_station.ik import ArmGeometry
from coffee_station.schemas import new_id


class CameraIntrinsics(BaseModel):
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float

    @classmethod
    def from_frame(cls, width: int, height: int) -> "CameraIntrinsics":
        focal = float(max(width, height))
        return cls(width=width, height=height, fx=focal, fy=focal, cx=width / 2.0, cy=height / 2.0)


class CameraExtrinsics(BaseModel):
    camera_id: int
    rotation_vector: list[float] = Field(min_length=3, max_length=3)
    translation_m: list[float] = Field(min_length=3, max_length=3)
    residual_rms_px: float | None = None
    sample_count: int = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ArmCalibration(BaseModel):
    robot_id: str
    base_height_m: float
    shoulder_to_elbow_m: float
    elbow_to_wrist_m: float
    wrist_to_tool_m: float
    joint_zero_offsets_deg: list[float] = Field(default_factory=lambda: [0.0] * 6, min_length=6, max_length=6)
    residual_rms_px: float | None = None
    sample_count: int = 0
    status: Literal["unfit", "fit"] = "unfit"
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def from_geometry(
        cls,
        robot_id: str,
        geometry: ArmGeometry,
        joint_zero_offsets_deg: list[float] | None = None,
        residual_rms_px: float | None = None,
        sample_count: int = 0,
        status: Literal["unfit", "fit"] = "fit",
    ) -> "ArmCalibration":
        return cls(
            robot_id=robot_id,
            base_height_m=geometry.base_height_m,
            shoulder_to_elbow_m=geometry.shoulder_to_elbow_m,
            elbow_to_wrist_m=geometry.elbow_to_wrist_m,
            wrist_to_tool_m=geometry.wrist_to_tool_m,
            joint_zero_offsets_deg=joint_zero_offsets_deg or [0.0] * 6,
            residual_rms_px=residual_rms_px,
            sample_count=sample_count,
            status=status,
        )

    def geometry(self) -> ArmGeometry:
        return ArmGeometry(
            base_height_m=self.base_height_m,
            shoulder_to_elbow_m=self.shoulder_to_elbow_m,
            elbow_to_wrist_m=self.elbow_to_wrist_m,
            wrist_to_tool_m=self.wrist_to_tool_m,
        )


class CalibrationSample(BaseModel):
    id: str = Field(default_factory=new_id)
    session_id: str
    camera_id: int
    timestamp: float
    joint_vector: list[float] = Field(min_length=6, max_length=6)
    pixel_u: float
    pixel_v: float
    frame_width: int
    frame_height: int
    tracker_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: Literal["tracker", "manual", "synthetic"] = "tracker"


class CalibrationFitResult(BaseModel):
    arm: ArmCalibration
    camera: CameraExtrinsics
    residual_rms_px: float
    sample_count: int
    converged: bool
    message: str
