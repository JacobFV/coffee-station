# Monocular Self-Calibration Spec

Status: implemented, feature-gated by `SELF_CALIBRATION_ENABLED`.

## Goal

Recover arm geometry and the camera-to-base transform from nothing but:

- A single ordinary webcam (no markers, no tags, no checkerboard, no human-typed coordinates).
- Synchronized joint telemetry (timestamps + commanded/measured joint angles).
- A short, agent-driven motion trajectory.

Output: a refined `ArmGeometry` (link lengths + per-joint zero offsets) and a 6-DOF camera extrinsic `T_cam_base`, persisted per-robot. Both are usable directly by `SimpleArmIK` and by 3D reasoning that projects world points into the agent's camera view.

Non-goal: replacing factory motor calibration. This recovers the kinematic and visual model on top of working encoders.

## Why this is solvable from one webcam

A monocular image cannot recover absolute scale from pixels alone. The trick is that the arm itself carries metric scale: joint encoders report angles in known units, and at least one link length only needs a single anchor to fix scale (in the simplest case, treat one link as a fixed prior with tight bounds from the printed STL; everything else is identifiable relative to it). Beyond that anchor, the kinematic chain provides the geometric constraints classical SfM gets from camera baseline.

So the unknowns split cleanly:

- `θ_arm`: link lengths (`base_height`, `shoulder_to_elbow`, `elbow_to_wrist`, `wrist_to_tool`) + per-joint angle offsets `ε_i` (6 values).
- `T_cam_base`: rotation `R` (3) + translation `t` (3).
- `K` intrinsics are initialized from frame dimensions with a pinhole focal-length prior.

Given a time series of `(q_t, u_t)` pairs — joint vector at time `t` and observed pixel position of the gripper tip — we minimize reprojection error:

```
L(θ_arm, T_cam_base) = Σ_t ρ( || π( K · T_cam_base · FK(q_t; θ_arm) ) − u_t ||² )
```

where `FK` is forward kinematics, `π` is perspective projection, and `ρ` is a Huber loss to tolerate tracking dropouts.

## Pipeline

### 1. Excitation trajectory (`src/coffee_station/calibration/excitation.py`)

Agent commands a smooth, slow, deliberately-informative joint trajectory. Requirements:

- Each joint moves through ≥60% of its safe range at least once.
- At least three sub-trajectories where one joint moves alone (decouples that joint's contribution).
- Workspace coverage in image: gripper visits ≥6 image quadrants and varies depth (some motions toward/away from camera).
- Bounded speed so tracking and frame timing stay aligned. Default target: ~15 s, 60 waypoints, `duration_s=0.25` per segment.

Implementation: a conservative fixed list of diverse joint-space poses spanning base sweep, reach, retraction, and wrist-roll variation. The poses are intentionally bounded for hardware safety and provide enough non-planar samples for the bounded reprojection fit.

### 2. Markerless gripper tracking (`src/coffee_station/calibration/tracker.py`)

No ArUco, no tag. The gripper is identified as **the coherent image-motion region nearest the forward-kinematics projection when a fitted `(θ_arm, T_cam_base)` estimate exists**, and as the dominant coherent motion during bootstrap. Pipeline per frame:

1. Compute dense optical flow against the previous frame with Farneback.
2. Predict the *expected* 2D velocity at each pixel under the current geometry estimate, by projecting the FK velocity of the gripper tip into the image and broadcasting.
3. Score each pixel by `1 − cos(observed_flow, predicted_flow)` + magnitude agreement. The connected region with the lowest aggregate score is the gripper hypothesis; its centroid is `u_t`.
4. Maintain a small appearance template (a learned patch around the centroid, refreshed every N frames with EMA) as a sanity check — if appearance drifts dramatically without motion explaining it, drop the frame.

Bootstrap: for the very first iteration there is no geometry estimate good enough to predict 2D motion. The agent solves this by commanding a single distinctive motion — base joint sweep with all other joints frozen — at startup. The only point in the image that traces a smooth arc whose pixel speed matches the commanded angular speed (up to an unknown radius) is the gripper. That arc seeds the tracker; subsequent passes refine.

### 3. Joint nonlinear optimization (`src/coffee_station/calibration/solver.py`)

Levenberg–Marquardt over `(θ_arm, T_cam_base)`. Implementation notes:

- Initial `θ_arm` = current `ArmGeometry` defaults (CAD priors). Tight bounds (±25%) on link lengths.
- Initial `T_cam_base` from a coarse PnP-like step: take three widely separated `(q_t, u_t)` samples, compute the predicted gripper 3D positions under the prior `θ_arm`, and solve P3P for the camera pose. Refined later jointly.
- Parameterize rotation as a 3-vector via Rodrigues to avoid quaternion normalization in the solver.
- Use SciPy `least_squares` with `method="trf"`, `loss="huber"`, `f_scale` set to ~3 px so single-frame tracking errors don't dominate.
- Residual scaling: divide pixel residuals by the local image gradient magnitude when available, so edges contribute more than flat regions.

### 4. Identifiability and degeneracies

- **Depth–scale ambiguity**: handled by anchoring one link length (default: `wrist_to_tool_m` from CAD, with a ±5% prior). All other geometry is then fully identifiable.
- **Camera-roll vs base-rotation**: degenerate if every motion is a pure base rotation — the camera could be tilted instead. The excitation trajectory's "joint solo" passes break this.
- **Planar trajectories**: if all gripper positions lie near a plane, camera position normal to that plane is poorly observed. The excitation trajectory deliberately includes out-of-plane moves.
- **Tracker losing the gripper**: handled by Huber loss + per-frame confidence; dropped frames are skipped, not interpolated.

### 5. Online refinement

After the initial fit, every subsequent agent loop step that contains a frame and a recent commanded pose contributes one sample. The service re-runs the bounded reprojection fit over the capped recent sample set, using tracker confidence as residual weights. This means:

- Geometry sharpens over time as more poses are seen.
- A bump that shifts the camera shows up as growing reprojection residuals and is corrected by the next weighted refit over recent samples.

### 6. Confidence + integration

- Each self-calibration status call exposes confidence (residual RMS in pixels, sample count, and update time).
- `SimpleArmIK` is constructed from the persisted `ArmGeometry`. Until the first successful fit, IK uses CAD defaults and the existing translation-offset calibration (`record_calibration_point`) as a fallback.
- `start_self_calibration` triggers the excitation trajectory and fit; `fit_self_calibration` fits from recorded samples; `get_self_calibration` returns the current state; `record_self_calibration_sample` records a synchronized joint-vector to screen-space observation.

## Storage

Add to `Storage`:

- `arm_geometry` row (singleton per robot id): link lengths, joint offsets, residual RMS, last updated.
- `camera_extrinsics` row per `camera_id`: R, t, intrinsics if estimated, residual RMS, last updated.
- `calibration_samples` table: `(timestamp, joint_vector, pixel_u, pixel_v, camera_id, tracker_confidence)` — capped at N most recent samples (default 5000) for retraining.

## Tests

- `tests/test_self_calibration.py`: synthetic ground truth, persistence, robot loading, and online observation/refit behavior.

## Phased delivery

1. Solver + storage with synthetic input (no real camera). Shipped.
2. Markerless dominant-motion tracker and conservative excitation trajectory. Shipped.
3. Agent tools (`start_self_calibration`, `fit_self_calibration`, `get_self_calibration`, `record_self_calibration_sample`). Shipped.
4. Load persisted fitted `ArmGeometry` in `build_robot`. Shipped.
5. Online weighted refinement and confidence reporting. Shipped.

The feature remains behind `SELF_CALIBRATION_ENABLED`, default off, because `start_self_calibration` commands robot motion.

## Open questions

- Intrinsics: current implementation initializes from frame dimensions using a pinhole focal-length prior.
- Multi-camera fusion: the codebase already supports multiple cameras. Each camera gets its own extrinsic; arm geometry is shared. The solver generalizes by summing residuals across cameras — out of scope for v1 but no architectural blocker.
- Gripper-tip definition: the FK tip and the visually-tracked centroid differ by a small offset (the centroid is the visual centroid of the moving region, not the tool tip). This offset is absorbed into `wrist_to_tool_m` and a small fixed 3D offset in the gripper frame, both jointly estimated.
