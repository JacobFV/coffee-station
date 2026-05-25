from __future__ import annotations

import math

import numpy as np

from coffee_station.ik import ArmGeometry

from .models import CameraExtrinsics, CameraIntrinsics


def rodrigues(rotation_vector: np.ndarray) -> np.ndarray:
    theta = float(np.linalg.norm(rotation_vector))
    if theta < 1e-12:
        return np.eye(3)
    axis = rotation_vector / theta
    x, y, z = axis
    skew = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    return np.eye(3) + math.sin(theta) * skew + (1.0 - math.cos(theta)) * (skew @ skew)


def forward_kinematics_tip(
    joints_deg: list[float],
    geometry: ArmGeometry,
    joint_zero_offsets_deg: list[float] | None = None,
) -> np.ndarray:
    offsets = joint_zero_offsets_deg or [0.0] * 6
    joints = [(float(joints_deg[i]) + float(offsets[i])) if i < len(joints_deg) else 0.0 for i in range(6)]
    base, shoulder, elbow, wrist_pitch = [math.radians(value) for value in joints[:4]]

    shoulder_angle = shoulder
    elbow_angle = shoulder + elbow
    tool_angle = shoulder + elbow + wrist_pitch

    wrist_radial = (
        geometry.shoulder_to_elbow_m * math.cos(shoulder_angle)
        + geometry.elbow_to_wrist_m * math.cos(elbow_angle)
    )
    wrist_z = (
        geometry.base_height_m
        + geometry.shoulder_to_elbow_m * math.sin(shoulder_angle)
        + geometry.elbow_to_wrist_m * math.sin(elbow_angle)
    )
    tip_radial = wrist_radial + geometry.wrist_to_tool_m * math.cos(tool_angle)
    tip_z = wrist_z + geometry.wrist_to_tool_m * math.sin(tool_angle)

    return np.array([tip_radial * math.cos(base), tip_radial * math.sin(base), tip_z], dtype=float)


def project_point(
    point_base: np.ndarray,
    intrinsics: CameraIntrinsics,
    extrinsics: CameraExtrinsics,
) -> tuple[float, float]:
    rotation = rodrigues(np.array(extrinsics.rotation_vector, dtype=float))
    translation = np.array(extrinsics.translation_m, dtype=float)
    point_cam = rotation @ point_base + translation
    z = max(float(point_cam[2]), 1e-6)
    u = intrinsics.fx * float(point_cam[0]) / z + intrinsics.cx
    v = intrinsics.fy * float(point_cam[1]) / z + intrinsics.cy
    return u, v


def geometry_from_vector(vector: np.ndarray) -> ArmGeometry:
    return ArmGeometry(
        base_height_m=float(vector[0]),
        shoulder_to_elbow_m=float(vector[1]),
        elbow_to_wrist_m=float(vector[2]),
        wrist_to_tool_m=float(vector[3]),
    )
