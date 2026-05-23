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
