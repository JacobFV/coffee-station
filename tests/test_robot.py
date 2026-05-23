from coffee_station.robot import RobotError, SimRobot, UnavailableRobot
from coffee_station.schemas import JointPose


def test_unavailable_robot_reports_and_refuses_motion():
    robot = UnavailableRobot("lerobot", "missing motors")
    robot.connect()

    state = robot.get_state()

    assert state["backend"] == "lerobot"
    assert state["connected"] is False
    assert state["unavailable"] is True
    try:
        robot.set_joint_pose(JointPose(joints=[0, 0, 0, 0, 0, 0]))
    except RobotError as exc:
        assert "missing motors" in str(exc)
    else:
        raise AssertionError("UnavailableRobot accepted a motion command")


def test_sim_robot_still_moves():
    robot = SimRobot()
    robot.connect()

    result = robot.set_joint_pose(JointPose(joints=[1, 2, 3, 4, 5, 6]))

    assert result["joints"] == [1, 2, 3, 4, 5, 6]
