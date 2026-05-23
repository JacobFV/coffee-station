from coffee_station.camera import CameraManager
from coffee_station.robot import RobotController, SimRobot
from coffee_station.settings import Settings
from coffee_station.storage import Storage
from coffee_station.tools import ToolRegistry


def test_bundle_tool_calls_schedules_and_runs_due_actions(tmp_path):
    settings = Settings(data_dir=tmp_path, camera_indices="")
    storage = Storage(tmp_path / "sessions.sqlite3")
    session = storage.create_session(model=settings.gemini_model)
    robot = RobotController(SimRobot())
    robot.connect()
    cameras = CameraManager(settings)
    tools = ToolRegistry(robot, cameras, storage)

    result = tools.dispatch(
        session.id,
        "bundle_tool_calls",
        {
            "calls": [
                {
                    "tool_name": "set_joint_pose",
                    "args": {"joints": [1, 2, 3, 4, 5, 6], "duration_s": 0.1},
                    "offset_s": 0,
                }
            ]
        },
    )

    assert len(result["scheduled"]) == 1
    completed = tools.run_due_actions()
    assert completed[0].status == "done"
    assert robot.state()["joints"] == [1, 2, 3, 4, 5, 6]


def test_stop_robot_cancels_queued_actions(tmp_path):
    settings = Settings(data_dir=tmp_path, camera_indices="")
    storage = Storage(tmp_path / "sessions.sqlite3")
    session = storage.create_session(model=settings.gemini_model)
    robot = RobotController(SimRobot())
    robot.connect()
    cameras = CameraManager(settings)
    tools = ToolRegistry(robot, cameras, storage)

    tools.dispatch(
        session.id,
        "set_joint_pose",
        {"joints": [9, 9, 9, 9, 9, 9], "schedule_offset_s": 30},
    )

    result = tools.dispatch(session.id, "stop_robot", {})

    assert result["stopped"] is True
    assert result["canceled_queued_actions"] == 1
    assert storage.queued_actions(session.id) == []


def test_calibration_tools_compute_mean_offset(tmp_path):
    settings = Settings(data_dir=tmp_path, camera_indices="")
    storage = Storage(tmp_path / "sessions.sqlite3")
    session = storage.create_session(model=settings.gemini_model)
    robot = RobotController(SimRobot())
    robot.connect()
    cameras = CameraManager(settings)
    tools = ToolRegistry(robot, cameras, storage)

    tools.dispatch(
        session.id,
        "record_calibration_point",
        {
            "believed_x": 0.10,
            "believed_y": 0.20,
            "believed_z": 0.30,
            "actual_x": 0.11,
            "actual_y": 0.18,
            "actual_z": 0.33,
        },
    )
    tools.dispatch(
        session.id,
        "record_calibration_point",
        {
            "believed_x": 0.20,
            "believed_y": 0.10,
            "believed_z": 0.40,
            "actual_x": 0.21,
            "actual_y": 0.08,
            "actual_z": 0.43,
        },
    )

    summary = tools.dispatch(session.id, "get_calibration", {})

    assert summary["sample_count"] == 2
    assert round(summary["offset"]["x"], 4) == 0.01
    assert round(summary["offset"]["y"], 4) == -0.02
    assert round(summary["offset"]["z"], 4) == 0.03


def test_hardware_tools_report_diagnostics(tmp_path):
    settings = Settings(data_dir=tmp_path, camera_indices="")
    storage = Storage(tmp_path / "sessions.sqlite3")
    session = storage.create_session(model=settings.gemini_model)
    robot = RobotController(SimRobot())
    robot.connect()
    cameras = CameraManager(settings)
    tools = ToolRegistry(robot, cameras, storage, settings)

    diagnostics = tools.dispatch(session.id, "diagnose_hardware", {})

    assert "serial_ports" in diagnostics
