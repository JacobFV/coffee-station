from __future__ import annotations

import math
from dataclasses import dataclass

from .schemas import JointPose, WorldPose


@dataclass(frozen=True)
class ArmGeometry:
    base_height_m: float = 0.065
    shoulder_to_elbow_m: float = 0.115
    elbow_to_wrist_m: float = 0.135
    wrist_to_tool_m: float = 0.095


class SimpleArmIK:
    """Geometric IK for SO-style 6-DOF arms.

    This maps world targets to a conservative six-joint command in degrees:
    base, shoulder, elbow, wrist_pitch, wrist_roll, gripper. It is intentionally
    small and inspectable; production setups should calibrate link lengths and
    limits for the exact printed arm and tool.
    """

    def __init__(self, geometry: ArmGeometry | None = None):
        self.geometry = geometry or ArmGeometry()

    def solve(self, pose: WorldPose) -> JointPose:
        g = self.geometry
        radial = math.hypot(pose.x, pose.y)
        base = math.degrees(math.atan2(pose.y, pose.x))

        wrist_radial = radial - g.wrist_to_tool_m * math.cos(math.radians(pose.pitch))
        wrist_z = pose.z - g.base_height_m - g.wrist_to_tool_m * math.sin(math.radians(pose.pitch))

        reach = math.hypot(wrist_radial, wrist_z)
        min_reach = 0.02
        max_reach = g.shoulder_to_elbow_m + g.elbow_to_wrist_m - 0.005
        reach = min(max(reach, min_reach), max_reach)

        cos_elbow = (
            reach * reach
            - g.shoulder_to_elbow_m * g.shoulder_to_elbow_m
            - g.elbow_to_wrist_m * g.elbow_to_wrist_m
        ) / (2.0 * g.shoulder_to_elbow_m * g.elbow_to_wrist_m)
        cos_elbow = max(-1.0, min(1.0, cos_elbow))
        elbow_inner = math.acos(cos_elbow)
        elbow = math.degrees(elbow_inner) - 180.0

        shoulder_line = math.atan2(wrist_z, wrist_radial)
        shoulder_offset = math.atan2(
            g.elbow_to_wrist_m * math.sin(elbow_inner),
            g.shoulder_to_elbow_m + g.elbow_to_wrist_m * math.cos(elbow_inner),
        )
        shoulder = math.degrees(shoulder_line - shoulder_offset)

        wrist_pitch = pose.pitch - shoulder - elbow
        wrist_roll = pose.roll
        gripper = pose.gripper if pose.gripper is not None else 0.0
        return JointPose(joints=[base, shoulder, elbow, wrist_pitch, wrist_roll, gripper])

    def offset(self, current: WorldPose, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0,
               droll: float = 0.0, dpitch: float = 0.0, dyaw: float = 0.0,
               gripper: float | None = None) -> WorldPose:
        return WorldPose(
            x=current.x + dx,
            y=current.y + dy,
            z=current.z + dz,
            roll=current.roll + droll,
            pitch=current.pitch + dpitch,
            yaw=current.yaw + dyaw,
            gripper=current.gripper if gripper is None else gripper,
        )
