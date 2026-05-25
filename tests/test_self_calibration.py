import numpy as np
import cv2

from coffee_station.calibration.service import SelfCalibrationService
from coffee_station.calibration.geometry import forward_kinematics_tip, project_point
from coffee_station.calibration.models import CalibrationSample, CameraIntrinsics
from coffee_station.calibration.solver import MonocularCalibrationSolver, default_extrinsics
from coffee_station.calibration.tracker import MarkerlessMotionTracker, TrackedPoint
from coffee_station.camera import CameraManager, CapturedFrame
from coffee_station.ik import ArmGeometry
from coffee_station.robot import RobotController, SimRobot, build_robot
from coffee_station.settings import Settings
from coffee_station.storage import Storage


def _synthetic_samples(session_id: str, geometry: ArmGeometry) -> list[CalibrationSample]:
    intrinsics = CameraIntrinsics.from_frame(1280, 720)
    extrinsics = default_extrinsics(0)
    poses = [
        [0, -25, 35, -10, 0, 25],
        [-35, -25, 35, -10, 0, 25],
        [35, -25, 35, -10, 0, 25],
        [0, -45, 65, -20, 0, 25],
        [0, 5, -12, 10, 0, 25],
        [-25, -42, 72, -30, 0, 25],
        [25, -42, 72, -30, 0, 25],
        [-20, -5, 20, -20, 0, 25],
        [20, -5, 20, -20, 0, 25],
        [0, -55, 88, -35, 0, 25],
        [-30, -12, 42, -35, 0, 25],
        [30, -12, 42, -35, 0, 25],
    ]
    samples = []
    for index, joints in enumerate(poses):
        point = forward_kinematics_tip(joints, geometry)
        u, v = project_point(point, intrinsics, extrinsics)
        samples.append(
            CalibrationSample(
                session_id=session_id,
                camera_id=0,
                timestamp=float(index),
                joint_vector=joints,
                pixel_u=u,
                pixel_v=v,
                frame_width=1280,
                frame_height=720,
                tracker_confidence=1.0,
                source="synthetic",
            )
        )
    return samples


def test_monocular_solver_fits_synthetic_reprojection():
    true_geometry = ArmGeometry(
        base_height_m=0.068,
        shoulder_to_elbow_m=0.119,
        elbow_to_wrist_m=0.132,
        wrist_to_tool_m=0.095,
    )
    samples = _synthetic_samples("session", true_geometry)
    result = MonocularCalibrationSolver("sim").fit(samples)

    assert result.converged
    assert result.residual_rms_px < 1.0
    assert np.isclose(result.arm.wrist_to_tool_m, true_geometry.wrist_to_tool_m, atol=0.006)


def test_storage_persists_self_calibration(tmp_path):
    storage = Storage(tmp_path / "sessions.sqlite3")
    session = storage.create_session(model="gemini-flash-latest")
    result = MonocularCalibrationSolver("sim").fit(_synthetic_samples(session.id, ArmGeometry()))

    storage.save_arm_calibration(result.arm)
    storage.save_camera_extrinsics(result.camera)
    for sample in _synthetic_samples(session.id, ArmGeometry()):
        storage.add_calibration_sample(sample)

    assert storage.get_arm_calibration("sim").status == "fit"
    assert storage.get_camera_extrinsics(0).camera_id == 0
    assert len(storage.list_calibration_samples(session.id, camera_id=0)) == 12


def test_robot_applies_persisted_calibration(tmp_path):
    storage = Storage(tmp_path / "sessions.sqlite3")
    result = MonocularCalibrationSolver("sim").fit(_synthetic_samples("session", ArmGeometry()))
    storage.save_arm_calibration(result.arm)

    robot = build_robot(Settings(data_dir=tmp_path, camera_indices=""), storage.get_arm_calibration("sim"))

    assert robot.state()["arm_calibration"]["status"] == "fit"
    assert robot.ik.geometry.wrist_to_tool_m == result.arm.wrist_to_tool_m


def test_robot_controller_apply_calibration_updates_state():
    controller = RobotController(SimRobot())
    controller.connect()
    result = MonocularCalibrationSolver("sim").fit(_synthetic_samples("session", ArmGeometry()))

    controller.apply_calibration(result.arm)

    assert controller.state()["arm_calibration"]["sample_count"] == 12


def test_markerless_tracker_prefers_expected_motion_region():
    tracker = MarkerlessMotionTracker()
    frame_a = np.zeros((120, 160, 3), dtype=np.uint8)
    frame_b = np.zeros((120, 160, 3), dtype=np.uint8)
    cv2.circle(frame_a, (30, 60), 8, (255, 255, 255), -1)
    cv2.circle(frame_b, (45, 60), 8, (255, 255, 255), -1)
    cv2.circle(frame_a, (120, 40), 8, (255, 255, 255), -1)
    cv2.circle(frame_b, (126, 40), 8, (255, 255, 255), -1)
    ok_a, jpeg_a = cv2.imencode(".jpg", frame_a)
    ok_b, jpeg_b = cv2.imencode(".jpg", frame_b)
    assert ok_a and ok_b

    assert tracker.observe(jpeg_a.tobytes()) is None
    point = tracker.observe(jpeg_b.tobytes(), expected_uv=(45, 60))

    assert point is not None
    assert abs(point.u - 45) < 20
    assert abs(point.v - 60) < 20


def test_online_observation_records_and_refits(tmp_path):
    settings = Settings(data_dir=tmp_path, camera_indices="", robot_backend="sim", self_calibration_enabled=True)
    storage = Storage(tmp_path / "sessions.sqlite3")
    session = storage.create_session(model="gemini-flash-latest")
    robot = RobotController(SimRobot())
    robot.connect()
    cameras = CameraManager(settings)
    service = SelfCalibrationService(settings, storage, robot, cameras)
    fit = MonocularCalibrationSolver("sim").fit(_synthetic_samples(session.id, ArmGeometry()))
    storage.save_arm_calibration(fit.arm)
    storage.save_camera_extrinsics(fit.camera)
    for sample in _synthetic_samples(session.id, ArmGeometry())[:7]:
        storage.add_calibration_sample(sample)
    robot.apply_calibration(fit.arm)
    robot.set_joint_pose([0, -25, 35, -10, 0, 25])

    class FakeTracker:
        def observe(self, jpeg, expected_uv=None):
            return TrackedPoint(u=640.0, v=360.0, confidence=0.8)

    service.trackers[0] = FakeTracker()
    frame = CapturedFrame(camera_id=0, timestamp=100.0, width=1280, height=720, jpeg=b"not-real-jpeg")

    sample = service.observe_agent_frame(session.id, frame)

    assert sample is not None
    assert sample.source == "tracker"
    assert storage.get_arm_calibration("sim").status == "fit"
