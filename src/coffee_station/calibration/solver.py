from __future__ import annotations

import math

import numpy as np

from coffee_station.ik import ArmGeometry

from .geometry import forward_kinematics_tip, geometry_from_vector, project_point
from .models import ArmCalibration, CalibrationFitResult, CalibrationSample, CameraExtrinsics, CameraIntrinsics


class CalibrationSolverError(RuntimeError):
    pass


def default_extrinsics(camera_id: int) -> CameraExtrinsics:
    return CameraExtrinsics(
        camera_id=camera_id,
        rotation_vector=[0.0, 0.0, 0.0],
        translation_m=[0.0, 0.0, 0.65],
    )


class MonocularCalibrationSolver:
    def __init__(self, robot_id: str, geometry_prior: ArmGeometry | None = None) -> None:
        self.robot_id = robot_id
        self.geometry_prior = geometry_prior or ArmGeometry()

    def fit(
        self,
        samples: list[CalibrationSample],
        intrinsics: CameraIntrinsics | None = None,
        initial_extrinsics: CameraExtrinsics | None = None,
    ) -> CalibrationFitResult:
        if len(samples) < 8:
            raise CalibrationSolverError("at least 8 calibration samples are required")
        camera_ids = {sample.camera_id for sample in samples}
        if len(camera_ids) != 1:
            raise CalibrationSolverError("single-camera fit requires samples from exactly one camera")
        first = samples[0]
        intrinsics = intrinsics or CameraIntrinsics.from_frame(first.frame_width, first.frame_height)
        initial_extrinsics = initial_extrinsics or default_extrinsics(first.camera_id)

        try:
            from scipy.optimize import least_squares
        except Exception as exc:
            raise CalibrationSolverError("scipy is required for self-calibration; install the project dependencies") from exc

        prior = self.geometry_prior
        initial = np.array(
            [
                prior.base_height_m,
                prior.shoulder_to_elbow_m,
                prior.elbow_to_wrist_m,
                prior.wrist_to_tool_m,
                *([0.0] * 6),
                *initial_extrinsics.rotation_vector,
                *initial_extrinsics.translation_m,
            ],
            dtype=float,
        )
        lower = np.array(
            [
                prior.base_height_m * 0.75,
                prior.shoulder_to_elbow_m * 0.75,
                prior.elbow_to_wrist_m * 0.75,
                prior.wrist_to_tool_m * 0.95,
                *([-25.0] * 6),
                -math.pi,
                -math.pi,
                -math.pi,
                -2.0,
                -2.0,
                0.05,
            ],
            dtype=float,
        )
        upper = np.array(
            [
                prior.base_height_m * 1.25,
                prior.shoulder_to_elbow_m * 1.25,
                prior.elbow_to_wrist_m * 1.25,
                prior.wrist_to_tool_m * 1.05,
                *([25.0] * 6),
                math.pi,
                math.pi,
                math.pi,
                2.0,
                2.0,
                3.0,
            ],
            dtype=float,
        )

        def unpack(params: np.ndarray) -> tuple[ArmGeometry, list[float], CameraExtrinsics]:
            geometry = geometry_from_vector(params[:4])
            offsets = [float(value) for value in params[4:10]]
            extrinsics = CameraExtrinsics(
                camera_id=first.camera_id,
                rotation_vector=[float(value) for value in params[10:13]],
                translation_m=[float(value) for value in params[13:16]],
            )
            return geometry, offsets, extrinsics

        def residuals(params: np.ndarray) -> np.ndarray:
            geometry, offsets, extrinsics = unpack(params)
            values: list[float] = []
            for sample in samples:
                point = forward_kinematics_tip(sample.joint_vector, geometry, offsets)
                u, v = project_point(point, intrinsics, extrinsics)
                weight = max(0.05, float(sample.tracker_confidence))
                values.append((u - sample.pixel_u) * weight)
                values.append((v - sample.pixel_v) * weight)

            # Priors anchor monocular scale and prevent zero-offset overfitting.
            values.extend(
                [
                    (geometry.base_height_m - prior.base_height_m) / (prior.base_height_m * 0.25),
                    (geometry.shoulder_to_elbow_m - prior.shoulder_to_elbow_m) / (prior.shoulder_to_elbow_m * 0.25),
                    (geometry.elbow_to_wrist_m - prior.elbow_to_wrist_m) / (prior.elbow_to_wrist_m * 0.25),
                    (geometry.wrist_to_tool_m - prior.wrist_to_tool_m) / (prior.wrist_to_tool_m * 0.05),
                ]
            )
            values.extend(float(offset) / 15.0 for offset in offsets)
            return np.array(values, dtype=float)

        result = least_squares(
            residuals,
            initial,
            bounds=(lower, upper),
            method="trf",
            loss="huber",
            f_scale=3.0,
            max_nfev=3000,
        )
        geometry, offsets, extrinsics = unpack(result.x)
        pixel_residuals = residuals(result.x)[: len(samples) * 2]
        rms = float(np.sqrt(np.mean(np.square(pixel_residuals)))) if len(pixel_residuals) else 0.0
        arm = ArmCalibration.from_geometry(
            robot_id=self.robot_id,
            geometry=geometry,
            joint_zero_offsets_deg=offsets,
            residual_rms_px=rms,
            sample_count=len(samples),
            status="fit",
        )
        extrinsics.residual_rms_px = rms
        extrinsics.sample_count = len(samples)
        return CalibrationFitResult(
            arm=arm,
            camera=extrinsics,
            residual_rms_px=rms,
            sample_count=len(samples),
            converged=bool(result.success),
            message=str(result.message),
        )
