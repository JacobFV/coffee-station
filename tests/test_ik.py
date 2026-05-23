import math

from coffee_station.ik import SimpleArmIK
from coffee_station.schemas import WorldPose


def test_simple_ik_returns_six_finite_joint_values():
    solver = SimpleArmIK()

    pose = solver.solve(WorldPose(x=0.18, y=0.02, z=0.14, pitch=-20.0, gripper=15.0))

    assert len(pose.joints) == 6
    assert all(math.isfinite(value) for value in pose.joints)
    assert pose.joints[-1] == 15.0
